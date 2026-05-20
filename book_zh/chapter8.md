# 第八章：多智能体协同与自定义工具链开发

在真实的企业级业务流中，依赖单一 Prompt 提示词引导大模型完成复杂的长链任务是极其不现实的。如果系统需要审计数据库的一张表、分析计算结果、根据异常值生成财务对账报告、并将报告打包通过邮件发送给对应的风控总监，单一 LLM 在面对如此繁杂的推理链时，很容易在中间步骤发生逻辑偏离或执行中断。为了应对这种长链、复杂的场景，FDE 部署了**多智能体协同（Multi-Agent Systems）** 架构。

在多智能体架构中，复杂的全局任务被拆解为若干个具备专业职能的 Agent（例如数据库查询 Agent、数据合规校验 Agent、SRE 报警 Agent），各 Agent 相互协作。它们通过绑定自定义的工具来操作云端接口，在共享状态机中协同读写，并具备出错自动修复的自愈能力。

本章将系统拆解多智能体协同的设计模式，提供一个完整的基于 LangGraph 状态管理思想的 Python 多 Agent 协作闭环，并给出 Token 消耗优化的生产实践经验。

---

## 1. 多智能体协同拓扑：Supervisor 架构

在生产环境中，多智能体之间的协作机制通常分为**主管-工人（Supervisor-Worker）**模型和**对等网络（Peer-to-Peer）**模型。其中，Supervisor 架构在企业级场景最受青睐：由一个中心主管 Agent 负责接收用户指令、拆解子任务并分发给具体执行的 Worker Agent，最后由主管 Agent 聚合结果输出。


<svg viewBox="0 0 750 250" width="100%" height="auto" style="background-color: #fafafa; border: 1px solid #e1e1e8; border-radius: 4px; margin: 20px 0; display: block;">
  <defs>
    <marker id="arrow" viewBox="0 0 10 10" refX="5" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
      <path d="M 0 0 L 10 5 L 0 10 z" fill="#333" />
    </marker>
  </defs>

  <!-- User Input -->
  <rect x="20" y="90" width="110" height="60" fill="#f4f4f6" stroke="#333" stroke-width="2" rx="6" />
  <text x="75" y="125" text-anchor="middle" font-family="sans-serif" font-weight="bold" font-size="11" fill="#111">用户原始诉求</text>

  <!-- Connection to Supervisor -->
  <line x1="130" y1="120" x2="200" y2="120" stroke="#333" stroke-width="1.5" marker-end="url(#arrow)" />

  <!-- Supervisor Node -->
  <rect x="210" y="65" width="160" height="110" fill="#e8f0fe" stroke="#1a73e8" stroke-width="2" rx="6" />
  <text x="290" y="90" text-anchor="middle" font-family="sans-serif" font-weight="bold" font-size="12" fill="#1a73e8">主管智能体 SUPERVISOR</text>
  <text x="290" y="115" text-anchor="middle" font-family="sans-serif" font-size="9" fill="#333">规划任务执行路径</text>
  <text x="290" y="130" text-anchor="middle" font-family="sans-serif" font-size="9" fill="#333">分发子任务并收集反馈</text>
  <text x="290" y="145" text-anchor="middle" font-family="monospace" font-size="8" fill="#1a73e8">全局状态机协调器</text>

  <!-- Split paths from Supervisor to Worker Agents -->
  <path d="M 370 120 L 460 60" fill="none" stroke="#333" stroke-width="1.5" marker-end="url(#arrow)" />
  <path d="M 370 120 L 460 120" fill="none" stroke="#333" stroke-width="1.5" marker-end="url(#arrow)" />
  <path d="M 370 120 L 460 180" fill="none" stroke="#333" stroke-width="1.5" marker-end="url(#arrow)" />

  <!-- Worker Agent 1: DBA Agent -->
  <rect x="470" y="30" width="220" height="50" fill="#fff" stroke="#666" rx="4" />
  <text x="580" y="50" text-anchor="middle" font-family="sans-serif" font-weight="bold" font-size="10">数据库 Worker (生成并执行 SQL)</text>
  <text x="580" y="68" text-anchor="middle" font-family="monospace" font-size="8" fill="#666">绑工具: postgres_query</text>

  <!-- Worker Agent 2: Validator Agent -->
  <rect x="470" y="95" width="220" height="50" fill="#fff" stroke="#666" rx="4" />
  <text x="580" y="115" text-anchor="middle" font-family="sans-serif" font-weight="bold" font-size="10">断言校验 Worker (质量与越界审计)</text>
  <text x="580" y="133" text-anchor="middle" font-family="monospace" font-size="8" fill="#666">绑工具: dbt_assert_runner</text>

  <!-- Worker Agent 3: SRE Agent -->
  <rect x="470" y="160" width="220" height="50" fill="#fff" stroke="#666" rx="4" />
  <text x="580" y="180" text-anchor="middle" font-family="sans-serif" font-weight="bold" font-size="10">通知推送 Worker (Slack 与 Pager)</text>
  <text x="580" y="198" text-anchor="middle" font-family="monospace" font-size="8" fill="#666">绑工具: pager_dispatch</text>
</svg>

为了防止各 Agent 在复杂的循环跳转中发生“死循环”或逻辑失控，FDE 采用类似于 **LangGraph** 的有向无环/环状图来约束状态转移，在每一次 Agent 执行完毕后对其输出状态进行严格规整。

---

## 2. 状态机协同实战：基于状态字典的 Agent 闭环

以下 Python 脚本完整模拟了 Supervisor 调度“数据库 Agent”与“数据校验 Agent”协同对账的过程，展示了多智能体之间如何通过共享的全局 State 字典进行数据通信。

```python
# multi_agent_orchestrator.py
from typing import Dict, TypedDict, List
import json

# 定义所有 Agent 共享的全局状态机上下文
class AgentState(TypedDict):
    original_query: str
    sql_query: str
    query_result: List[Dict]
    validation_status: str
    final_answer: str
    errors: List[str]

# 数据库执行智能体绑定的工具
def execute_sql_tool(state: AgentState) -> AgentState:
    print("\n[DB Agent] 收到执行指令，开始审计 SQL 语句...")
    query = state.get("sql_query", "")
    
    # 简易防护安全注入
    if "DROP" in query.upper() or "DELETE" in query.upper():
        state["errors"].append("检测到高危 SQL 指令，拒绝执行。")
        state["validation_status"] = "FAILED"
        return state
        
    print(f"[DB Agent] 正在安全隔离网内执行: {query}")
    # 模拟返回的物理数据行
    state["query_result"] = [
        {"customer_id": "CUST_01", "balance": 50000},
        {"customer_id": "CUST_02", "balance": 12000}
    ]
    state["validation_status"] = "PENDING_VALIDATION"
    return state

# 质量校验智能体绑定的工具
def validate_results_tool(state: AgentState) -> AgentState:
    print("\n[Validator Agent] 收到校验请求，对数据明细进行断言审计...")
    results = state.get("query_result", [])
    
    # 审查每一行数据是否符合业务财务规范
    for row in results:
        if row.get("balance", 0) < 0:
            state["errors"].append(f"数据异常：客户 {row.get('customer_id')} 余额为负数。")
            state["validation_status"] = "FAILED"
            return state
            
    state["validation_status"] = "PASSED"
    return state

# 主管智能体 (Orchestrator Control Loop)
def run_orchestrator(query: str):
    # 初始化全局状态
    state: AgentState = {
        "original_query": query,
        "sql_query": "SELECT customer_id, balance FROM accounts WHERE balance > 10000",
        "query_result": [],
        "validation_status": "START",
        "final_answer": "",
        "errors": []
    }
    
    # 步骤 1：触发 DB 提取
    state = execute_sql_tool(state)
    if "FAILED" in state["validation_status"]:
        print(f"[Supervisor] 调度流强行终止，原因: {state['errors'][-1]}")
        return
        
    # 步骤 2：触发数据校验
    state = validate_results_tool(state)
    if state["validation_status"] == "FAILED":
        print(f"[Supervisor] 调度流强行终止，原因: {state['errors'][-1]}")
        return
        
    # 步骤 3：主管收纳汇总，输出最终答复
    if state["validation_status"] == "PASSED":
        state["final_answer"] = f"已审计 {len(state['query_result'])} 条客户账目，数据通过质量校验规则。"
        print(f"\n[Supervisor] 流程流转完毕: {state['final_answer']}")

if __name__ == "__main__":
    run_orchestrator("帮我查询余额大于 10000 的客户数据")
```

---

## 3. 错误自愈与 Token 消耗治理

让多智能体在企业生产环境中长周期运行，需要解决健壮性与运行成本的现实问题。

### 1. 工具调用异常自愈（Self-Healing）
如果在执行 SQL 或调用 REST 接口时，由于多打了一个分号或数据库表字段拼写错误而报错，优秀的系统不应该直接崩溃。FDE 会捕获底层抛出的异常堆栈，将错误日志作为新的 Prompt 投喂给执行 Agent，指导大模型自主修正代码。

```
[Agent 提请 SQL] -> 数据库引擎返回: Column "cust_name" does not exist
[主管 Agent 捕获异常] -> 作为 Prompt 重新提交: "数据库报错字段不存在，请检查元数据重新修正。"
[Agent 自我检视修复] -> "抱歉，真实列名为 customer_name，我已重新生成 SQL 提请执行。"
```

### 2. 消息剪枝与上下文治理（Context Management）
随着 Agent 在回路中不断流转，Prompt 交互记录会迅速膨胀，导致 API 调用成本激增、且响应延迟不断爬升。FDE 常用以下策略限制上下文体积：
* **历史剪枝（Message Pruning）**：当某个 Worker Agent 执行完子任务后，主管 Agent 仅在其全局 State 中记录其汇总的结论 JSON，并把之前几十轮冗长的数据通信明细从 LLM 上下文中彻底剪除。
* **总结重构（Summary Memory）**：每隔固定步数，调用一次轻量级模型对当前排查的轨迹进行语义压缩，用一段几百字的总结替换所有的历史聊天链。

---

## 本章小结

多智能体系统是企业级应用走向“全自动运行”的必由之路。通过建立以 Supervisor 为核心的全局状态机、编写具备错误诊断能力的自愈型工具组件，并实施严格的上下文消息剪枝，FDE 能够帮助企业搭建出坚固、能够自动应对现场复杂技术突发情况的自动化作业管道。
