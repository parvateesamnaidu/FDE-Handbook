# 第五章：混合云架构与安全着陆区设计

在企业级客户的私有基础设施中部署高价值数据平台，必须对云网络安全及“着陆区（Landing Zone）”架构有极深的设计认知。大型企业或金融机构绝不允许任何外部软件暴露在公网，或者在不设防的网络中直连其核心数据库。相反，他们通常会要求所有系统运行在隔离的私有子网内、通过安全隧道或专用物理网闸进行跨网连接，并基于最小特权原则对云端资源访问实施严格的身份授权。

本章将详细拆解基于 GCP 的安全着陆区网络架构设计——特别是共享 VPC（Shared VPC）拓扑与 GKE 私有集群，并提供完整的 Terraform 代码以实现基础设施的声明式自动部署。

---

## 1. 经典着陆区网络架构：共享 VPC (Shared VPC)

在大型企业中，网络管理与应用开发通常是完全分离的。网络资源（如 VPC、子网、路由及防火墙规则）由中心化的**宿主项目（Host Project）**统一管控；而具体的业务系统则运行在独立的**服务项目（Service Project）**中，通过共享接口挂载到宿主项目的网卡上。


<svg viewBox="0 0 750 240" width="100%" height="auto" style="background-color: #fafafa; border: 1px solid #e1e1e8; border-radius: 4px; margin: 20px 0; display: block;">
  <defs>
    <marker id="arrow" viewBox="0 0 10 10" refX="5" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
      <path d="M 0 0 L 10 5 L 0 10 z" fill="#333" />
    </marker>
  </defs>

  <!-- Host Project Boundary -->
  <rect x="20" y="30" width="310" height="180" fill="#f4f4f6" stroke="#333" stroke-width="2" rx="6" />
  <text x="175" y="50" text-anchor="middle" font-family="sans-serif" font-weight="bold" font-size="12" fill="#111">宿主项目 HOST PROJECT (网络运维团队管理)</text>
  
  <rect x="40" y="70" width="270" height="120" fill="#fff" stroke="#666" stroke-dasharray="3" rx="4" />
  <text x="175" y="90" text-anchor="middle" font-family="sans-serif" font-weight="bold" font-size="10" fill="#333">共享 VPC (Shared VPC: 10.0.0.0/16)</text>
  
  <rect x="60" y="110" width="105" height="60" fill="#e8f0fe" stroke="#1a73e8" rx="3" />
  <text x="112" y="130" text-anchor="middle" font-family="sans-serif" font-weight="bold" font-size="9" fill="#1a73e8">GKE 节点子网</text>
  <text x="112" y="145" text-anchor="middle" font-family="monospace" font-size="8" fill="#555">10.100.0.0/20</text>

  <rect x="185" y="110" width="105" height="60" fill="#e8f0fe" stroke="#1a73e8" rx="3" />
  <text x="237" y="130" text-anchor="middle" font-family="sans-serif" font-weight="bold" font-size="9" fill="#1a73e8">核心业务子网</text>
  <text x="237" y="145" text-anchor="middle" font-family="monospace" font-size="8" fill="#555">10.200.0.0/20</text>

  <!-- Share Action -->
  <line x1="330" y1="120" x2="410" y2="120" stroke="#1a73e8" stroke-width="2" marker-end="url(#arrow)" />
  <text x="370" y="110" text-anchor="middle" font-family="sans-serif" font-size="9" fill="#1a73e8" font-weight="bold">跨项目子网共享</text>

  <!-- Service Project Boundary -->
  <rect x="420" y="30" width="310" height="180" fill="#e3f2fd" stroke="#1a73e8" stroke-width="2" rx="6" />
  <text x="575" y="50" text-anchor="middle" font-family="sans-serif" font-weight="bold" font-size="12" fill="#1a73e8">服务项目 SERVICE PROJECT (业务部署)</text>

  <rect x="450" y="80" width="250" height="110" fill="#fff" stroke="#1a73e8" rx="4" />
  <text x="575" y="105" text-anchor="middle" font-family="sans-serif" font-weight="bold" font-size="11" fill="#111">私有 GKE 容器集群</text>
  <text x="575" y="125" text-anchor="middle" font-family="monospace" font-size="9" fill="#666">节点网络挂载至宿主子网</text>
  <text x="575" y="140" text-anchor="middle" font-family="monospace" font-size="9" fill="#666">Master 控制面私网 IP</text>
</svg>

### 共享 VPC 架构的独特优势：
1. **安全审计集中化**：宿主项目锁死防火墙与路由变更权限，使得客户的网安部门能集中审计所有的出口与入口流量，而无需阻碍应用开发。
2. **完全私有化**：部署在服务项目中的 GKE 计算节点与数据库都仅分配私网 IP。外部进入的流量必须经过受控网关（如 Cloud Interconnect 或 Private Service Connect）。

---

## 2. 基础设施即代码：搭建安全着陆区 Terraform

为了确保客户环境搭建的绝对一致性并排除手工配置隐患，FDE 通过 Terraform 进行声明式的基础设施定义。

### 1. 宿主项目（Host Project）网络定义
以下代码用于在宿主项目中划定共享 VPC 及专属的 GKE 私网子网：

```hcl
# host_network.tf
provider "google" {
  project = var.host_project_id
  region  = var.region
}

resource "google_compute_network" "shared_vpc" {
  name                    = "shared-vpc-network"
  auto_create_subnetworks = false
}

resource "google_compute_subnetwork" "gke_subnet" {
  name          = "gke-private-subnet"
  ip_cidr_range = "10.100.0.0/20"
  network       = google_compute_network.shared_vpc.id
  region        = var.region

  # 启用私网 Google 访问通道 (GKE 节点访问 GCP 基础 API)
  private_ip_google_access = true

  # 为 GKE Pods 动态分配的辅助网段
  secondary_ip_range {
    range_name    = "gke-pods-range"
    ip_cidr_range = "172.16.0.0/16"
  }

  # 为 GKE Services 动态分配的辅助网段
  secondary_ip_range {
    range_name    = "gke-services-range"
    ip_cidr_range = "172.17.0.0/20"
  }
}
```

### 2. 服务项目（Service Project）私有 GKE 集群定义
以下代码配置了在业务服务项目中搭建的 GKE 私有集群，其物理子网挂载在上述宿主项目的共享 VPC 上：

```hcl
# service_gke.tf
provider "google" {
  project = var.service_project_id
  region  = var.region
}

resource "google_container_cluster" "private_cluster" {
  name     = "fde-private-gke-cluster"
  location = var.region

  # 指定挂载在宿主项目下的网络和子网
  network    = "projects/${var.host_project_id}/global/networks/${google_compute_network.shared_vpc.name}"
  subnetwork = "projects/${var.host_project_id}/regions/${var.region}/subnetworks/${google_compute_subnetwork.gke_subnet.name}"

  # 开启私有集群配置 (禁止节点分配公网 IP)
  private_cluster_config {
    enable_private_nodes    = true
    enable_private_endpoint = true
    master_ipv4_cidr_block  = "172.18.0.0/28"
  }

  ip_allocation_policy {
    cluster_secondary_range_name  = "gke-pods-range"
    services_secondary_range_name = "gke-services-range"
  }

  # 启用 Workload Identity 安全身份绑定
  workload_identity_config {
    workload_pool = "${var.service_project_id}.svc.id.goog"
  }

  node_config {
    machine_type = "e2-standard-4"
    metadata = {
      disable-legacy-endpoints = "true"
    }
  }
}
```

---

## 3. 安全凭证映射：GCP 工作负载身份（Workload Identity）

在高度受控的企业环境中，静态服务账号密钥（JSON 文件）是被严密管控的重大风险点。静态密钥文件一旦随代码被误提交至 Git 仓库，或者从系统内部泄露出去，外部黑客就能长驱直入获取所有的云端存储。

FDE 彻底弃用静态密钥，转而使用 GCP 的 **Workload Identity** 机制。该机制允许 GKE 内部的 Kubernetes 服务账号（KSA）与云端的 Google 服务账号（GSA）进行无感安全映射，从而让 Pod 无需密钥文件，仅凭动态生成的短期令牌便可直接访问 BigQuery、Cloud Storage 或 Vertex AI 等云端接口。

```hcl
# workload_identity.tf
resource "google_service_account" "platform_gsa" {
  project      = var.service_project_id
  account_id   = "fde-data-processor-gsa"
  display_name = "应用专用的 GCP 服务账号"
}

# 授权 Kubernetes 中的特定 ServiceAccount 冒充该 GCP 服务账号的权限
resource "google_service_account_iam_member" "workload_identity_binding" {
  service_account_id = google_service_account.platform_gsa.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "serviceAccount:${var.service_project_id}.svc.id.goog[fde-namespace/data-processor-ksa]"
}
```

### Kubernetes Service Account 的安全注解配置
在 GKE 集群内，FDE 通过在 ServiceAccount 配置清单中添加特定注解，将其与 GCP 角色绑定：

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: data-processor-ksa
  namespace: fde-namespace
  annotations:
    # 与云端 GSA 服务账号完成映射
    iam.gke.io/gcp-service-account: "fde-data-processor-gsa@service-project-id.iam.gserviceaccount.com"
```

这确保了在 GKE 容器中运行的程序无需挂载任何 JSON 密钥，也能安全且透明地拉取 BigQuery 表或调用大模型 API。

---

## 本章小结

建立安全、高度隔离的云端着陆区是确保数据系统在企业场景安全着陆的关键前提。通过严密设计 Host-Service 项目下的共享 VPC、搭建完全私有的 GKE 隔离容器环境，并基于 Workload Identity 进行去密钥化的安全身份打通，FDE 成功在严苛的企业合规规范下，为平台构建了坚不可摧的安全边界。
