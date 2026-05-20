# 第六章：高安全边界与企业合规落地 (VPC SC)

在企业级安全架构中，仅仅依靠身份和访问控制管理（IAM）通常被认为是不够的。如果静态凭证意外泄露，或者 IAM 策略配置不当，即便攻击者仅持有一个只读权限账号，也可能将企业内部的敏感数据搬运至公网上他自己控制的云存储中（即数据外泄 Data Exfiltration）。在诸如金融、银行或医疗等强合规环境中，企业要求实施物理及网络层面的双重隔离边界。

在 Google Cloud 中，这一边界是通过 **VPC 服务边界（VPC Service Controls，简称 VPC SC）** 实现的。VPC SC 通过在敏感 API（如 Cloud Storage、BigQuery、Vertex AI）外侧拉起一道虚拟的物理沙箱边界，确保即便账号权限被破解，数据也绝对无法跨越网络边界进行传输。

本章将详细剖析 VPC SC 的防护机理，给出使用 Terraform 配置服务边界的完整清单，并提供遭遇边界拦截时的排查日志分析 playbook。

---

## 1. VPC Service Controls 服务边界防火墙原理

VPC SC 可以被视作是托管谷歌 API 的“接口级防火墙”。一旦某项服务被纳入边界的防护范围，任何对该服务接口的调用，除非其请求物理上源自边界内部的授权子网，或者完全符合预先设定的 Ingress 规则，否则一律会被强行拦截。


<svg viewBox="0 0 750 250" width="100%" height="auto" style="background-color: #fafafa; border: 1px solid #e1e1e8; border-radius: 4px; margin: 20px 0; display: block;">
  <defs>
    <marker id="arrow" viewBox="0 0 10 10" refX="5" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
      <path d="M 0 0 L 10 5 L 0 10 z" fill="#333" />
    </marker>
  </defs>

  <!-- Outside (Public Web / Attacker) -->
  <rect x="20" y="70" width="160" height="110" fill="#ffebee" stroke="#c62828" stroke-width="2" rx="6" />
  <text x="100" y="95" text-anchor="middle" font-family="sans-serif" font-weight="bold" font-size="12" fill="#c62828">外部公网 (互联网攻击者)</text>
  <text x="100" y="125" text-anchor="middle" font-family="sans-serif" font-size="10" fill="#333">凭证意外泄漏 /</text>
  <text x="100" y="140" text-anchor="middle" font-family="sans-serif" font-size="10" fill="#333">公网匿名 API 提请</text>

  <!-- Block Arrow -->
  <line x1="180" y1="125" x2="280" y2="125" stroke="#c62828" stroke-width="2.5" marker-end="url(#arrow)" />
  <text x="230" y="115" text-anchor="middle" font-family="sans-serif" font-size="10" fill="#c62828" font-weight="bold">被 VPC-SC 物理阻断</text>

  <!-- VPC Service Controls Perimeter -->
  <rect x="290" y="30" width="440" height="190" fill="#e8f5e9" stroke="#2e7d32" stroke-width="3" stroke-dasharray="6" rx="8" />
  <text x="510" y="55" text-anchor="middle" font-family="sans-serif" font-weight="bold" font-size="13" fill="#2e7d32">VPC SERVICE CONTROLS 安全边界沙箱</text>

  <!-- Inside Project -->
  <rect x="310" y="80" width="180" height="120" fill="#fff" stroke="#666" rx="4" />
  <text x="400" y="105" text-anchor="middle" font-family="sans-serif" font-weight="bold" font-size="11" fill="#111">服务项目 Service Project</text>
  <text x="400" y="130" text-anchor="middle" font-family="monospace" font-size="9" fill="#555">私有 GKE 计算集群</text>
  <text x="400" y="150" text-anchor="middle" font-family="monospace" font-size="9" fill="#555">受信任的主机节点</text>

  <!-- Protected APIs -->
  <rect x="520" y="80" width="190" height="120" fill="#e3f2fd" stroke="#1a73e8" rx="4" />
  <text x="615" y="105" text-anchor="middle" font-family="sans-serif" font-weight="bold" font-size="11" fill="#1a73e8">受保护的托管云服务</text>
  <text x="615" y="135" text-anchor="middle" font-family="monospace" font-size="9" fill="#333">bigquery.googleapis.com</text>
  <text x="615" y="155" text-anchor="middle" font-family="monospace" font-size="9" fill="#333">storage.googleapis.com</text>
  <text x="615" y="175" text-anchor="middle" font-family="monospace" font-size="9" fill="#333">vertexai.googleapis.com</text>
</svg>

### VPC SC 的核心管理原语：
1. **受保护的 API（Restricted Services）**：明确哪些云服务接口（如 BigQuery、Vertex AI）需要被纳入物理边界管控。一旦添加，外部请求默认全部切断。
2. **安全级别 (Access Levels)**：通过来源公网 IP（如客户总部出口 IP）或者特定受控设备的证书状态，对从边界外部发起的请求进行合规认证。
3. **入站与出站策略 (Ingress/Egress Rules)**：当需要与其他 VPC 或不同组织的存储桶进行通信时，通过精准描述“允许谁、从哪个子网、向哪个目的地、调用哪个具体方法”来打通安全通道。

---

## 2. 基础设施即代码：Terraform 部署服务边界

由于 VPC SC 属于组织（Organization）级别的安全策略，配置失误可能导致整个公司的云端接口瞬间停摆。因此，所有的边界变更必须通过 Terraform 规范化，实施严格的代码审查。

### Terraform 安全边界配置
以下代码演示了如何创建一个组织级策略，并建立一条服务边界以保护 BigQuery、Cloud Storage 及 Vertex AI：

```hcl
# vpc_service_controls.tf

# 定义组织级的访问策略上下文
resource "google_access_context_manager_access_policy" "org_policy" {
  parent = "organizations/${var.org_id}"
  title  = "fde-security-policy"
}

# 创建允许访问的安全级别 (定义受信任的总部公网 CIDR 网段)
resource "google_access_context_manager_access_level" "corporate_ips" {
  parent = google_access_context_manager_access_policy.org_policy.name
  name   = "accessPolicies/${google_access_context_manager_access_policy.org_policy.name}/accessLevels/corporate_ips"
  title  = "企业总部受信 IP 组"

  basic {
    conditions {
      ip_subnetworks = ["192.168.100.0/24", "10.0.10.0/24"]
    }
  }
}

# 构建物理服务边界，包含服务项目并锁定敏感 API
resource "google_access_context_manager_service_perimeter" "security_perimeter" {
  parent = google_access_context_manager_access_policy.org_policy.name
  name   = "accessPolicies/${google_access_context_manager_access_policy.org_policy.name}/servicePerimeters/fde_secure_perimeter"
  title  = "FDE 生产高安全防线边界"

  status {
    # 强制隔离保护的 Service Project 编号
    resources = ["projects/${var.service_project_number}"]

    # 纳入物理隔离的托管接口
    restricted_services = [
      "bigquery.googleapis.com",
      "storage.googleapis.com",
      "vertexai.googleapis.com"
    ]

    # 入站白名单：允许来自受信 IP 组的用户对存储桶执行只读下载
    ingress_policies {
      ingress_from {
        identity_type = "ANY_IDENTITY"
        sources {
          access_level = google_access_context_manager_access_level.corporate_ips.name
        }
      }
      ingress_to {
        resources = ["*"]
        operations {
          service_name = "storage.googleapis.com"
          method_selectors {
            method = "google.storage.objects.get"
          }
        }
      }
    }
  }
}
```

---

## 3. 边界排错与“干跑诊断”机制（Dry-Run Mode）

当请求因为违反 VPC SC 边界而被强行阻断时，谷歌云端接口会给应用程序返回极其精简的 `403 Forbidden` 权限错误。为了让排查效率不沦为盲人摸象，FDE 需要建立科学的故障排查步骤。

### 1. 强制使用 Dry-Run 测试模式
在将边界完全应用之前，FDE **必须且只能**先配置为 **Dry-Run（干跑测试）模式**。在该模式下，发生越界请求时，系统不会真的执行阻断动作，而是仅向 Cloud Logging 审计日志中写入一条拦截元数据。这允许 FDE 可以在真实业务流量下充分测试策略，排查合规错误。

### 2. 通过审计日志定位边界拦截元数据
当拦截发生时，FDE 在宿主项目的 Cloud Logging 日志控制台中使用以下日志过滤器抓取报错报文：

```sql
-- 锁定 VPC-SC 拦截详情的专属日志过滤器
resource.type="audited_resource"
protoPayload.status.code=7
protoPayload.metadata."@type"="type.googleapis.com/google.cloud.audit.VpcServiceControlsAuditMetadata"
```

#### 抓取到的元数据 Payload 核心诊断属性：
* `callerIp`：提请 API 请求的发起端 IP 地址（例如：是哪个 client 机房发起的请求）。
* `serviceName`：被调用的 Google 服务名（如 `vertexai.googleapis.com`）。
* `violationReason`：被拦截的具体原因（例如 `NO_MATCHING_ACCESS_LEVEL` IP 不匹配，或 `RESOURCES_NOT_IN_SAME_SERVICE_PERIMETER` 关联的两方项目不在同一个沙箱边界内）。
* `egressViolationInfo`：如果是由于违反出站规则引发的拦截，此节点会指明请求正试图将数据流出到哪一个外部项目的目标存储桶（Target Project）中。

根据拦截详情，FDE 可以在代码中快速修正 Ingress 或 Egress 策略，待彻底消除 Dry-Run 拦截记录后，再切换到 Enforced（正式生效）状态，以实现安全边界的平滑落地。

---

## 本章小结

VPC 服务边界（VPC SC）是保障企业云端数据资产安全的最高防线。通过设计清晰的服务边界拓扑、编写符合最小访问特权的 Terraform 策略，并利用 Dry-Run 干跑排错日志过滤器实现敏捷的策略优化，FDE 能极大地缩短现场上线调试周期，并为系统构筑出金融级别的合规隔离防线。
