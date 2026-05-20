# 第十章：行业实战案例：高安全 AI 投顾平台部署

本章将前文各章所涉及的顾问式思维、安全着陆区配置、现代数据工程、混合检索 RAG 及多智能体协同等核心技术栈，统一融合成一个完整的、端到端的真实行业部署案例。我们将跟随 FDE 的步伐，为一个全球顶尖金融机构——**Apex 环球财富集团（Apex Global Wealth）**，在私有云中从零到一落地部署一套具备金融合规品质的 AI 投顾平台。

我们将详细解构其安全网络沙箱、数据库清洗模型、dbt 增量构建、RAG 向量检索管道及 LangGraph 调度编排的全局实现，为企业级 FDE 交付提供全套落地蓝图。

---

## 1. 行业案例背景与全局系统架构

Apex 环球财富集团需要一套能够分析数百万行客户资产底账、交叉检索庞大市场研究 PDF 报告（内含复杂数据表），并为高净值用户自动生成符合合规审计标准的个性化理财报告的 AI 系统。

### 核心指标与设计红线
* **金融合规红线**：所有客户资产明细严禁流出私有云边界，禁止向公网第三方模型 API 传输数据。所有 API 调用必须处于 VPC Service Controls 沙箱边界内。
* **高精度零幻觉**：生成的财务数据必须具有 100% 忠实度，严禁在理财报告中捏造或臆测任何资产余额、转账历史等事实。
* **交付效能 SLA**：单份综合理财报告的自动生成与审核阻断流程必须在 5 分钟内处理完毕，代替以往长达 48 小时的人工处理周期。


<svg viewBox="0 0 750 280" width="100%" height="auto" style="background-color: #fafafa; border: 1px solid #e1e1e8; border-radius: 4px; margin: 20px 0; display: block;">
  <defs>
    <marker id="arrow" viewBox="0 0 10 10" refX="5" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
      <path d="M 0 0 L 10 5 L 0 10 z" fill="#333" />
    </marker>
  </defs>

  <!-- VPC Service Controls Boundary -->
  <rect x="15" y="15" width="720" height="250" fill="#e8f5e9" stroke="#2e7d32" stroke-width="2.5" stroke-dasharray="8" rx="8" />
  <text x="375" y="35" text-anchor="middle" font-family="sans-serif" font-weight="bold" font-size="12" fill="#2e7d32">VPC SERVICE CONTROLS 安全隔离沙箱边界</text>

  <!-- Host Network Project Subnets -->
  <rect x="30" y="55" width="220" height="190" fill="#f4f4f6" stroke="#333" stroke-width="1.5" rx="6" />
  <text x="140" y="75" text-anchor="middle" font-family="sans-serif" font-weight="bold" font-size="11" fill="#111">共享 VPC (宿主项目 Host Project)</text>
  
  <rect x="45" y="95" width="190" height="60" fill="#fff" stroke="#666" rx="4" />
  <text x="140" y="115" text-anchor="middle" font-family="sans-serif" font-weight="bold" font-size="10">GKE 私网子网</text>
  <text x="140" y="130" text-anchor="middle" font-family="monospace" font-size="8" fill="#555">10.100.0.0/20 (完全内网)</text>

  <rect x="45" y="170" width="190" height="60" fill="#fff" stroke="#666" rx="4" />
  <text x="140" y="190" text-anchor="middle" font-family="sans-serif" font-weight="bold" font-size="10">数据库专用子网</text>
  <text x="140" y="205" text-anchor="middle" font-family="monospace" font-size="8" fill="#555">10.200.0.0/20 (PSC 隧道)</text>

  <!-- Service Project (GKE Platform) -->
  <rect x="280" y="55" width="220" height="190" fill="#e3f2fd" stroke="#1a73e8" stroke-width="1.5" rx="6" />
  <text x="390" y="75" text-anchor="middle" font-family="sans-serif" font-weight="bold" font-size="11" fill="#1a73e8">业务服务项目 (Service Project)</text>
  
  <rect x="295" y="95" width="190" height="135" fill="#fff" stroke="#1a73e8" rx="4" />
  <text x="390" y="115" text-anchor="middle" font-family="sans-serif" font-weight="bold" font-size="10">LangGraph 调度节点</text>
  <text x="390" y="135" text-anchor="middle" font-family="monospace" font-size="8" fill="#666">SQL 查询 Agent (PG 主库)</text>
  <text x="390" y="155" text-anchor="middle" font-family="monospace" font-size="8" fill="#666">RAG 解析 Agent (LlamaParse)</text>
  <text x="390" y="175" text-anchor="middle" font-family="monospace" font-size="8" fill="#666">Supervisor 主控状态机</text>
  <text x="390" y="195" text-anchor="middle" font-family="monospace" font-size="8" fill="#1a73e8">Workload Identity 去密钥化</text>

  <!-- Protected Services (BigQuery & Vertex) -->
  <rect x="530" y="55" width="180" height="190" fill="#fff9c4" stroke="#fbc02d" stroke-width="1.5" rx="6" />
  <text x="620" y="75" text-anchor="middle" font-family="sans-serif" font-weight="bold" font-size="11" fill="#b79008">隔离保护的托管 API</text>

  <rect x="545" y="95" width="150" height="60" fill="#fff" stroke="#fbc02d" rx="4" />
  <text x="620" y="115" text-anchor="middle" font-family="sans-serif" font-weight="bold" font-size="10">BigQuery 仓储</text>
  <text x="620" y="130" text-anchor="middle" font-family="monospace" font-size="8" fill="#666">Medallion 金牌资产事实</text>

  <rect x="545" y="170" width="150" height="60" fill="#fff" stroke="#fbc02d" rx="4" />
  <text x="620" y="190" text-anchor="middle" font-family="sans-serif" font-weight="bold" font-size="10">Vertex AI (Gemini)</text>
  <text x="620" y="205" text-anchor="middle" font-family="monospace" font-size="8" fill="#666">模型推理与向量索引</text>

  <!-- Flow Connections -->
  <path d="M 250 120 L 280 120" fill="none" stroke="#333" stroke-width="1.5" marker-end="url(#arrow)" />
  <path d="M 500 120 L 530 120" fill="none" stroke="#333" stroke-width="1.5" marker-end="url(#arrow)" />
</svg>

---

## 2. 系统分步落地指引

FDE 在现场按照标准的产品落地生命周期，展开如下五步交付：

### 第一步：搭建高安全云端基础（Landing Zone）
使用第五、六章定义的 Terraform 代码声明，在 Host-Service 项目下初始化 Shared VPC，创建完全杜绝公网的私有 GKE 集群，并绑定 Workload Identity，最后在外侧套上 VPC Service Controls perimeter，完成物理网络安全边界闭锁。

### 第二步：资产数据清洗（dbt Transformation）
* FDE 编写 dbt 增量构建模型，将遗留数据库中的海量转账流水和持仓快照抽取并转化为银牌层的事实与维度模型。
* 针对倾斜的 `UNKNOWN` 散客账号，在计算层应用 PySpark 加盐方案进行 Shuffle 性能调优，避免集群 OOM。
* 执行 `dbt test` 强制完成非空、主键唯一及字段约束值域检验。

### 第三步：研报 RAG 管道搭建（RAG Pipelines）
* 将 PDF 格式的宏观研报提交至 LlamaParse 进行结构化解析，将其中的表格完整复原为 Markdown matrix。
* 数据切片后投喂给 Vertex AI 向量数据库生成稠密向量索引，并配合传统的 BM25 稀疏索引搭建起双路检索链路。

### 第四步：多智能体平台调度（LangGraph Agents）
* 在 GKE 中部署 LangGraph 多智能体协同程序。
* 由 **Supervisor 智能体** 统一协调：
  1. 唤醒 **数据库 Worker Agent**：使用自定义工具提取当前受审用户的全部资产底单。
  2. 唤醒 **研报检索 Worker Agent**：使用双路混合检索及 RRF 互惠重排算法，捞取最匹配该用户持仓变动趋势的宏观研报段落。
  3. 唤醒 **生成 Worker Agent**：将资产数据与研报上下文融合，撰写理财建议报告。

### 第五步：持续打分与线上监控（Inner-Outer Loops）
使用第九章编写的自动化 LLM-as-a-Judge 评估 suite，对生产日志进行 Faithfulness（忠实度）异步跑分。若发现大模型生成的段落未能获得召回上下文的支持，触发熔断器阻断报告下发，并向合规风控大屏推送异常预警。

---

## 3. 生产部署核心配置文件与代码清单

以下是在 Apex 环球财富集团生产环境中实际部署通过的关键配置文件，代表了高强度 FDE 交付的标准。

### 1. 资产数据增量清洗 dbt 模型
以下 dbt 脚本用于将原始账户变更流水转化为干净的银牌层每日持仓余额事实表，并配置分区以提升查询效能：

```sql
-- models/silver/silver_portfolio_balances.sql
{{ config(
    materialized='incremental',
    unique_key='balance_id',
    partition_by={
      "field": "as_of_date",
      "data_type": "date",
      "granularity": "day"
    }
) }}

WITH raw_transactions AS (
    SELECT * FROM {{ ref('bronze_raw_transactions') }}
    {% if is_incremental() %}
    -- 仅增量计算上一次执行之后产生的新交易流水
    WHERE transaction_timestamp >= (SELECT MAX(transaction_timestamp) FROM {{ this }})
    {% endif %}
),

cleaned_balances AS (
    SELECT
        MD5(CONCAT(customer_id, '|', transaction_date)) AS balance_id,
        customer_id,
        CAST(transaction_date AS DATE) AS as_of_date,
        -- 使用窗口函数计算每日滚动账户累计余额
        SUM(amount) OVER (
            PARTITION BY customer_id 
            ORDER BY transaction_timestamp 
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        ) AS current_balance,
        transaction_timestamp AS last_updated_at
    FROM
        raw_transactions
)

SELECT * FROM cleaned_balances
```

### 2. GKE 隔离环境 Agent 容器部署清单
以下 Kubernetes 部署清单将 LangGraph supervisor 进程部署在 GKE 私有节点上，绑定专用的 Workload Identity 账户以获取云端资源访问权限：

```yaml
# deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: fde-supervisor-deployment
  namespace: fde-secure-platform
  labels:
    app: fde-supervisor
spec:
  replicas: 3
  selector:
    matchLabels:
      app: fde-supervisor
  template:
    metadata:
      labels:
        app: fde-supervisor
    spec:
      # 挂载绑定了 Workload Identity 的 K8s 安全账号
      serviceAccountName: data-processor-ksa
      containers:
      - name: platform-orchestrator
        image: gcr.io/apex-global-wealth/fde-orchestrator:v1.2.0
        ports:
        - containerPort: 8080
        env:
        - name: PROJECT_ID
          value: "apex-service-project"
        - name: LOCATION
          value: "us-central1"
        resources:
          limits:
            memory: "4Gi"
            cpu: "2000m"
          requests:
            memory: "2Gi"
            cpu: "1000m"
        # 遵循生产级别硬化容器安全上下文规范
        securityContext:
          allowPrivilegeEscalation: false
          readOnlyRootFilesystem: true
          runAsNonRoot: true
          runAsUser: 10001
```

该清单排除了静态凭证 JSON Key 的挂载，对计算容器进行了非 Root 用户硬化，并锁定根文件系统为只读（ReadOnly），这符合顶级金融企业的合规交付要求。

---

## 本章小结

交付企业级的 AI 平台绝非是写出几个能工作的 demo，而是要将安全边界隔离、极致的数据流清洗转换、双路并联的重排检索以及多智能体协同调度熔断完美融合成一个咬合紧密的机器。通过将 Apex 环球财富集团的 Shared VPC 网络、dbt 资产汇总、向量+稀疏 RAG 检索以及有向状态机的纠错自愈串联为一体，FDE 为行业客户提供了一个完全闭环、高度合规的高品质交付示范。
