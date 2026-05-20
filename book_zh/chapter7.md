# 第七章：企业级 RAG (检索增强生成) 架构蓝图

在企业级真实数据集上落地生成式人工智能应用，检索架构的设计是决定成败的核心。如果简单粗暴地将成百上千个 PDF 文件直接塞入大语言模型的上下文窗口（Context Window），不仅会导致极高的 Token 账单和严重的幻觉，还会频繁触发上下文溢出。为了将系统扩展到海量企业级文档，FDE 团队构建并部署了 **RAG（检索增强生成）** 架构。

一个生产级别的企业 RAG 系统必须具备以下能力：能够解析复杂的多模态文档（例如包含复杂表格、拓扑图和扫描件的 PDF 手册）；能够在数百万级别的数据集中通过混合检索（Hybrid Search）快速定位上下文；并且所有接口访问必须被安全隔离在物理网闸内部。

本章将详细解构企业级 RAG 架构设计，提供基于 LlamaParse 的多维文档结构化解析脚本，并用 Python 实现混合检索结果重排的核心算法——互惠排名融合（RRF）。

---

## 1. 双路混合检索与重排架构

为了确保检索的查全率（Recall）和查准率（Precision）同时达到上线标准，企业级 RAG 平台必须抛弃单一的向量检索，转而实施双路混合检索：
1. **稠密向量检索（Semantic Dense Search）**：通过大模型（如 Vertex AI text-embeddings API）生成多维向量，擅长捕捉句子的深层语义关联。即便用户输入的提问词与文档原文没有一个词是相同的，也能基于语义相似度把答案捞出来。
2. **稀疏关键字检索（Sparse Keyword Search）**：通过传统的统计学词频算法（如 BM25）。它在匹配特定的产品序列号、专业缩写代码、物料 ID 时表现极其精准，能完美弥补向量空间对精准字符匹配的钝化缺陷。


<svg viewBox="0 0 750 250" width="100%" height="auto" style="background-color: #fafafa; border: 1px solid #e1e1e8; border-radius: 4px; margin: 20px 0; display: block;">
  <defs>
    <marker id="arrow" viewBox="0 0 10 10" refX="5" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
      <path d="M 0 0 L 10 5 L 0 10 z" fill="#333" />
    </marker>
  </defs>

  <!-- Query Input -->
  <rect x="20" y="90" width="120" height="60" fill="#f4f4f6" stroke="#333" stroke-width="2" rx="6" />
  <text x="80" y="115" text-anchor="middle" font-family="sans-serif" font-weight="bold" font-size="12" fill="#111">用户原始提问</text>
  <text x="80" y="132" text-anchor="middle" font-family="monospace" font-size="9" fill="#555">"GKE PSC 安全配置"</text>

  <!-- Query Split -->
  <path d="M 140 120 L 220 60" fill="none" stroke="#333" stroke-width="1.5" marker-end="url(#arrow)" />
  <path d="M 140 120 L 220 180" fill="none" stroke="#333" stroke-width="1.5" marker-end="url(#arrow)" />

  <!-- Dense Pipeline -->
  <rect x="230" y="30" width="180" height="60" fill="#fff" stroke="#1a73e8" rx="4" />
  <text x="320" y="55" text-anchor="middle" font-family="sans-serif" font-weight="bold" font-size="11" fill="#1a73e8">稠密向量路 (Dense)</text>
  <text x="320" y="72" text-anchor="middle" font-family="monospace" font-size="9" fill="#666">Vertex AI 向量索引 (语义)</text>

  <!-- Sparse Pipeline -->
  <rect x="230" y="150" width="180" height="60" fill="#fff" stroke="#1a73e8" rx="4" />
  <text x="320" y="175" text-anchor="middle" font-family="sans-serif" font-weight="bold" font-size="11" fill="#1a73e8">稀疏关键字路 (Sparse)</text>
  <text x="320" y="192" text-anchor="middle" font-family="monospace" font-size="9" fill="#666">BM25 / Elasticsearch (关键字)</text>

  <!-- Connect to Fusion -->
  <path d="M 410 60 L 490 120" fill="none" stroke="#333" stroke-width="1.5" marker-end="url(#arrow)" />
  <path d="M 410 180 L 490 120" fill="none" stroke="#333" stroke-width="1.5" marker-end="url(#arrow)" />

  <!-- Fusion & Rerank -->
  <rect x="500" y="90" width="220" height="70" fill="#e8f5e9" stroke="#2e7d32" stroke-width="2" rx="6" />
  <text x="610" y="115" text-anchor="middle" font-family="sans-serif" font-weight="bold" font-size="12" fill="#2e7d32">互惠排名融合 (RRF)</text>
  <text x="610" y="132" text-anchor="middle" font-family="sans-serif" font-size="10" fill="#333">与 Cross-Encoder 深度重排</text>
  <text x="610" y="147" text-anchor="middle" font-family="monospace" font-size="9" fill="#666">输出 Top-K 精准上下文</text>
</svg>

双路检索获得的结果往往评分体系不同（向量相似度分值通常在 0 到 1 之间，而 BM25 词频得分是一个无上限的正数）。FDE 通过互惠排名融合算法（RRF）摒弃绝对得分值，转而根据排名的倒数进行加权合并，并在最后通过 Cross-Encoder 评分模型进行精细二次重排，将最精确的黄金片段投喂给大模型。

---

## 2. 基于 LlamaParse 的多维文档结构化解析

企业的 PDF 手册和分析报告中往往夹杂着复杂的表格或双栏排版布局。普通的文本切片器（Text Splitter）会粗暴地按行切分表格，使得同行中跨单元格的字段关系支离破碎。FDE 引入 **LlamaParse** 这一强力解析引擎，将多模态 PDF 原生转化为结构化的 Markdown 格式，完美保留表格的可读语法。

以下是完整的 Python 摄取清洗及 Vertex AI 向量化处理脚本：

```python
# ingestion_pipeline.py
import os
from llama_parse import LlamaParse
from langchain.text_splitter import MarkdownTextSplitter
from google.cloud import aiplatform

def initialize_vertex_ai(project_id, location):
    aiplatform.init(project=project_id, location=location)

def parse_pdf_to_markdown(file_path, api_key):
    # 初始化 LlamaParse，强制开启高精度的 Markdown 表格输出模式
    parser = LlamaParse(
        api_key=api_key,
        result_type="markdown",
        verbose=True,
        language="zh"  # 识别中文
    )
    documents = parser.load_data(file_path)
    return documents[0].text

def split_markdown_content(markdown_text):
    # 根据 Markdown 独有的标题级别（如 ###）和段落边界进行语义切分
    text_splitter = MarkdownTextSplitter(
        chunk_size=1000,
        chunk_overlap=150
    )
    chunks = text_splitter.split_text(markdown_text)
    return chunks

def generate_vertex_embeddings(texts, project_id):
    # 借助 Vertex AI 的 text-embedding 接口生成高维向量
    from vertexai.language_models import TextEmbeddingModel
    
    model = TextEmbeddingModel.from_pretrained("text-embedding-004")
    embeddings = model.get_embeddings(texts)
    return [e.values for e in embeddings]

# 模拟管道调度
if __name__ == "__main__":
    API_KEY = os.environ.get("LLAMA_CLOUD_API_KEY", "mock_key")
    PROJECT_ID = "service-project-id"
    
    # 1. 文档解析
    print("正在通过 LlamaParse 逆向解析 PDF 表格...")
    raw_md = parse_pdf_to_markdown("specs.pdf", API_KEY)
    
    # 2. 文本分片
    print("正在按 Markdown 语义进行文本分片...")
    chunks = split_markdown_content(raw_md)
    
    # 3. 向量生成
    print("正在调用 Vertex AI 接口进行稠密向量化...")
    embeddings = generate_vertex_embeddings(chunks[:3], PROJECT_ID)
    print(f"成功生成 {len(embeddings)} 个向量，向量维度: {len(embeddings[0])}")
```

---

## 3. 双路检索排序合并：互惠排名融合（RRF）

互惠排名融合（Reciprocal Rank Fusion，简称 RRF）是一种在信息检索领域极其经典的算法。它无需关心两路检索算法输出的具体评分绝对值，仅根据每个文档在两条检索结果队列中的相对名次进行评分融合。

一个文档 $d$ 在文档集 $D$ 中的 RRF 最终得分计算公式为：
$$RRF\_Score(d) = \sum_{m \in M} \frac{1}{k + r_m(d)}$$
其中，$r_m(d)$ 表示文档 $d$ 在检索策略 $m$ 中排出的名次（从 1 开始）；$k$ 是一个常数（在工业界通常设定为 60），用于平滑排名靠后的脏数据对整体权重造成的过度稀释。

以下是该算法的 Python 核心实现：

```python
# reciprocal_rank_fusion.py

def reciprocal_rank_fusion(dense_results, sparse_results, k=60):
    """
    对稠密向量检索与稀疏关键字检索排出的文档队列进行融合重排
    
    dense_results: 向量检索排出的文档 ID 列表 (有序)
    sparse_results: 关键字检索排出的文档 ID 列表 (有序)
    """
    rrf_scores = {}
    
    # 累加向量检索队列的得分倒数
    for rank, doc_id in enumerate(dense_results, start=1):
        if doc_id not in rrf_scores:
            rrf_scores[doc_id] = 0.0
        rrf_scores[doc_id] += 1.0 / (k + rank)
        
    # 累加关键词检索队列的得分倒数
    for rank, doc_id in enumerate(sparse_results, start=1):
        if doc_id not in rrf_scores:
            rrf_scores[doc_id] = 0.0
        rrf_scores[doc_id] += 1.0 / (k + rank)
        
    # 按照融合成的 RRF 分数从高到低进行倒序排列
    sorted_docs = sorted(rrf_scores.items(), key=lambda item: item[1], reverse=True)
    return sorted_docs

# 执行验证
if __name__ == "__main__":
    # 模拟两路检索各自吐出的文档 ID
    dense_hits = ["doc_A", "doc_B", "doc_C", "doc_D"]
    sparse_hits = ["doc_C", "doc_A", "doc_E", "doc_F"]
    
    fused_results = reciprocal_rank_fusion(dense_hits, sparse_hits, k=60)
    print("融合后的 RRF 最终文档名次及得分:")
    for doc, score in fused_results:
        print(f" - {doc}: {score:.5f}")
```

在上面的验证中，由于 `doc_C` 和 `doc_A` 在两路队列中都获得了很高的检索排位，它们的 RRF 汇总分数处于绝对领先，因此会被作为最终的召回 context 送入大模型，保证了知识找寻的完整性。

---

## 本章小结

构建工业级的 RAG 检索流水线是连接海量数据资产与前沿生成式大模型的关键枢纽。通过利用 LlamaParse 彻底破解 PDF 中的复杂表格，将稠密向量检索与稀疏关键字检索通过互惠排名融合（RRF）算法进行高精度归并，并在高安全 perimeters 内部稳定交付，FDE 成功在严苛的保密合规限制下，为 AI 智能体搭建出了兼顾性能与效率的“企业外脑”。
