# 第九章：大模型系统的科学评估与线上校验

在传统的软件工程中，系统的输出是确定性（Deterministic）的：只要输入相同的参数，代码永远会执行相同的逻辑。然而，在生成式人工智能（Generative AI）时代，系统的输出变成了概率性（Probabilistic）的。一个在今天表现完美的 Agent 提示词，在明天可能因为模型底层的微调升级、或者检索知识库上下文的细微变化，而产生偏离预期的输出。在企业级高价值场景下，让未加校验的大模型应用裸奔上线，无异于给生产环境埋下一颗隐形炸弹。

为了解决这一痛点，FDE 团队引入了科学的双环评估架构：**开发阶段的内环迭代（Inner Loop）**与**生产阶段的外环监控（Outer Loop）**。

本章将系统剖析大模型系统的双环评估生命周期，详细推导 RAG 核心质量指标，提供一个基于 Python 的 LLM-as-a-Judge（大模型裁判）自动化跑分套件，并解密 AutoSxS（双模型横向比对）的设计原理。

---

## 1. 评估体系生命周期：内环 vs. 外环

为了保障模型在从原型设计到正式上线的全生命周期中始终处于质量控制下，评估流程必须分阶段闭环运行：


<svg viewBox="0 0 750 250" width="100%" height="auto" style="background-color: #fafafa; border: 1px solid #e1e1e8; border-radius: 4px; margin: 20px 0; display: block;">
  <defs>
    <marker id="arrow" viewBox="0 0 10 10" refX="5" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
      <path d="M 0 0 L 10 5 L 0 10 z" fill="#333" />
    </marker>
  </defs>

  <!-- Inner Loop (Dev-time) -->
  <rect x="30" y="40" width="310" height="170" fill="#f4f4f6" stroke="#333" stroke-width="2" rx="6" />
  <text x="185" y="60" text-anchor="middle" font-family="sans-serif" font-weight="bold" font-size="12" fill="#111">评估内环 (开发调试 Inner Loop)</text>
  
  <rect x="50" y="80" width="270" height="40" fill="#fff" stroke="#666" rx="4" />
  <text x="185" y="105" text-anchor="middle" font-family="sans-serif" font-size="10">基于黄金数据集 (Golden Dataset) 跑分</text>
  
  <rect x="50" y="140" width="270" height="40" fill="#fff" stroke="#666" rx="4" />
  <text x="185" y="165" text-anchor="middle" font-family="sans-serif" font-size="10">覆盖 50~100 条高价值边界测试用例</text>

  <!-- Transition -->
  <line x1="340" y1="125" x2="400" y2="125" stroke="#333" stroke-width="2" marker-end="url(#arrow)" />
  <text x="370" y="115" text-anchor="middle" font-family="sans-serif" font-size="9" fill="#666" font-weight="bold">版本交付</text>

  <!-- Outer Loop (Production-time) -->
  <rect x="410" y="40" width="310" height="170" fill="#e8f5e9" stroke="#2e7d32" stroke-width="2" rx="6" />
  <text x="565" y="60" text-anchor="middle" font-family="sans-serif" font-weight="bold" font-size="12" fill="#2e7d32">评估外环 (生产运行 Outer Loop)</text>
  
  <rect x="430" y="80" width="270" height="40" fill="#fff" stroke="#2e7d32" rx="4" />
  <text x="565" y="105" text-anchor="middle" font-family="sans-serif" font-size="10">异步监听生产环境用户真实对话日志</text>
  
  <rect x="430" y="140" width="270" height="40" fill="#fff" stroke="#2e7d32" rx="4" />
  <text x="565" y="165" text-anchor="middle" font-family="sans-serif" font-size="10">自动计算指标，低于报警阈值则阻断发布</text>
</svg>

1. **开发调试内环（Inner Loop）**：发生在开发期。工程师在修改 Agent 提示词或重构检索算法时，会通过评估脚本在包含 50~100 条的核心“黄金数据集（Golden Dataset）”上反复跑分，确保本次优化没有引起系统性能退化（Regression）。
2. **生产监控外环（Outer Loop）**：发生在系统上线后。异步数据管道持续抓取线上真实用户的对话日志，以自动化形式提请评估管道进行千级别的数据打分。当整体忠实度指标跌破阈值时，自动触发报警或系统熔断。

---

## 2. 评估 RAG 质量的三大黄金指标

FDE 衡量一个 RAG 系统表现是否合格，主要依赖以下三个数学化指标：
1. **忠实度（Faithfulness，也称 Groundedness）**：评估模型生成的答复是否**完全且仅**基于召回的上下文。该指标用于杜绝大模型根据自己预训练的记忆胡编乱造（幻觉）。
$$\text{忠实度} = \frac{\text{生成答案中能被召回上下文支撑的陈述句个数}}{\text{生成答案中所有陈述句的总个数}}$$
2. **答案相关性（Answer Relevance）**：评估生成的响应是否直接且精准地回答了用户的原始提问（避免答非所问）。
$$\text{答案相关性} = \text{Cosine\_Similarity}(\text{Embedding}(答案), \text{Embedding}(提问))$$
3. **上下文召回率（Context Recall）**：评估检索组件是否成功抓取到了解答用户提问所需的**所有**关键信息。
$$\text{上下文召回率} = \frac{\text{黄金参考答案中能被召回上下文支撑的陈述句个数}}{\text{黄金参考答案中所有陈述句的总个数}}$$

---

## 3. 代码实战：基于 LLM-as-a-Judge 的自动化打分套件

为了在大规模数据流中自动计算上述指标，FDE 采用 **LLM-as-a-Judge** 模式。通过使用能力极其出众的大模型（如 Gemini 1.5 Pro），配置带有极高逻辑约束的判定 Prompt，来审核被测模型（如 Gemini 1.5 Flash）的生成结果。

以下是实现自动化“忠实度评估”的完整 Python 脚本：

```python
# evaluation_suite.py
import json
import os
from google.cloud import aiplatform
from vertexai.generative_models import GenerativeModel

def get_judge_response(prompt: str) -> str:
    # 使用旗舰级的 Gemini Pro 作为裁判模型
    model = GenerativeModel("gemini-1.5-pro-002")
    response = model.generate_content(prompt)
    return response.text

# 判定大模型忠实度的系统级 Prompt 模板
JUDGE_TEMPLATE = """
您是一个精细的系统审计专家。请认真分析提供的 [参考上下文] 与 [待评估答案]，判定该答案的忠实度得分。

[参考上下文]
{context}

[待评估答案]
{answer}

判定步骤：
1. 提取 [待评估答案] 中的所有独立陈述句 (Discrete Statements)。
2. 逐一判定每个陈述句是否直接、无偏差地得到 [参考上下文] 的信息支持。
3. 计算最终的忠实度得分（被支持的陈述句数 / 陈述句总数）。

请**务必只返回**一个合法的 JSON 报文，无需 markdown 包裹，结构如下：
{{
  "statements": [
    {{
      "statement": "Shared VPC 的子网范围是 10.100.0.0/20",
      "supported": true,
      "explanation": "直接符合参考上下文中第一句的描述。"
    }}
  ],
  "faithfulness_score": 1.0
}}
"""

def evaluate_faithfulness(context: str, answer: str) -> float:
    formatted_prompt = JUDGE_TEMPLATE.format(context=context, answer=answer)
    raw_response = get_judge_response(formatted_prompt)
    
    try:
        # 去除 markdown 标记并解析 JSON
        clean_json = raw_response.strip().replace("```json", "").replace("```", "")
        data = json.loads(clean_json)
        return data.get("faithfulness_score", 0.0)
    except Exception as e:
        print(f"解析裁判模型输出失败: {e}")
        return 0.0

# 模拟评估流程
if __name__ == "__main__":
    mock_context = (
        "Shared VPC 子网地址段为 10.100.0.0/20。"
        "GKE 启用了 Workload Identity 机制来绑定云端角色，完全避免了静态 JSON 密钥文件的配置。"
    )
    
    # 模拟一个完全合规的 faithful 答复
    good_answer = "我们通过 GKE Workload Identity 实现角色映射，无需静态 JSON 密钥文件。"
    score_1 = evaluate_faithfulness(mock_context, good_answer)
    print(f"合规回答的忠实度得分: {score_1:.2f}")

    # 模拟一个夹杂了外部幻觉的 unfaithful 答复
    bad_answer = "Shared VPC 子网地址段为 10.100.0.0/20，并且我们需要通过 IPSec VPN 连接到 AWS VPC。"
    score_2 = evaluate_faithfulness(mock_context, bad_answer)
    print(f"夹杂幻觉的回答的忠实度得分: {score_2:.2f}")
```

---

## 4. 升级保障：双模型横向比对 AutoSxS (Side-by-Side)

在系统升级、或更换更低成本的模型以降低推理开销时（例如将模型底座从 Gemini Pro 替换为 Gemini Flash），我们需要确保新模型在复杂边缘场景下的表现不会退化。为此，FDE 广泛采用 **AutoSxS（自动化双模型侧边比对）** 模式。

在 AutoSxS 评估中，裁判大模型在不被告知模型 A 和模型 B 身份的前提下，面对相同的 [用户提问] 和 [检索上下文]，直接对 [模型 A 生成的答复] 和 [模型 B 生成的答复] 进行横向对比打分。

### 1. AutoSxS 判定 Prompt 模板

```markdown
您是一个公正的系统升级评审专家。请分析以下 [用户提问]、[检索上下文]，并对比 [模型 A] 和 [模型 B] 的回答，判定谁是优胜者。

[用户提问]
{query}

[检索上下文]
{context}

[模型 A 的回答]
{answer_a}

[模型 B 的回答]
{answer_b}

比对标准：
1. 正确性 (Correctness)：哪一个模型的回答更符合上下文事实？是否包含常识错误？
2. 完整性 (Completeness)：哪一个模型完整回答了提问的所有子要点？
3. 简洁性 (Conciseness)：哪一个模型的表述更精炼，不包含无意义的废话和过度包装？
4. 安全合规 (Safety)：回答是否符合企业级安全合规防线？

请输出 JSON 报文，格式如下：
{{
  "winner": "A" / "B" / "TIE",
  "reason": "请给出非常具体的获胜理由，详细指出模型 B 比模型 A 好在哪些词汇和逻辑上。"
}}
```

### 2. AutoSxS 自动化运行脚本

通过运行以下 Python 脚本，FDE 可以在回归测试集中自动计算新旧模型之间的**胜率（Win-Rate）**，以此提供数据支撑的上线决策。

```python
# autosxs_runner.py
import json
from vertexai.generative_models import GenerativeModel

AUTOSXS_TEMPLATE = """
您是一个公正的系统升级评审专家。请分析以下 [用户提问]、[检索上下文]，并对比 [模型 A] 和 [模型 B] 的回答，判定谁是优胜者。

[用户提问]
{query}

[检索上下文]
{context}

[模型 A 的回答]
{answer_a}

[模型 B 的回答]
{answer_b}

比对标准：
1. 正确性 (Correctness)：哪一个模型的回答更符合上下文事实？
2. 完整性 (Completeness)：哪一个模型完整回答了提问的所有子要点？
3. 简洁性 (Conciseness)：哪一个模型的表述更精炼？

请输出 JSON 报文，格式如下：
{{
  "winner": "A",
  "reason": "模型 A 获胜的理由..."
}}
"""

def run_autosxs(query: str, context: str, answer_a: str, answer_b: str) -> dict:
    prompt = AUTOSXS_TEMPLATE.format(
        query=query,
        context=context,
        answer_a=answer_a,
        answer_b=answer_b
    )
    
    # 采用 Gemini 1.5 Pro 作为公正裁判
    model = GenerativeModel("gemini-1.5-pro-002")
    response = model.generate_content(prompt)
    
    try:
        clean_json = response.text.strip().replace("```json", "").replace("```", "")
        return json.loads(clean_json)
    except Exception as e:
        return {"winner": "TIE", "reason": f"解析异常: {e}"}

# 测试 AutoSxS 评估
if __name__ == "__main__":
    result = run_autosxs(
        query="如何为 GKE 集群配置身份鉴权？",
        context="推荐使用 GCP Workload Identity 将 KSA 映射到 GSA，从而免去管理静态 JSON 密钥文件的安全风险。",
        answer_a="我们推荐配置 Google Cloud 的 Workload Identity 机制，通过将 GKE 内部的 Kubernetes 服务账号绑定到云端的 IAM 服务账号，在 Pod 运行时动态获取凭证，避免了存储静态 JSON 密钥所带来的泄露隐患，这是企业级最安全的安全实践。",
        answer_b="可以通过在 Pod 容器里挂载并使用 Service Account 的 JSON 密钥文件来配置身份鉴权。"
    )
    print(f"AutoSxS 判定结果: {result['winner']}")
    print(f"获胜原因说明: {result['reason']}")
```

通过在一批代表性用例上并行触发上述评估，FDE 能够获取新版本模型相对于旧版本的**相对提升指数**与**安全防线合规率**，杜绝大模型系统因底层更新引起的任何“无预警崩溃”。

---

## 本章小结

构建具备自我校验能力的大模型系统是企业走向自动化生产的关键。通过精细设计 Inner-Outer 双环评估闭环，严格衡量 Faithful 忠实度与 Context Recall 召回率，并利用旗舰模型作为 LLM-as-a-Judge 实施规模化的自动化打分与 AutoSxS 升级判定，FDE 能够帮助企业在大模型的不确定性中牢牢抓取确定性的运行品质。
