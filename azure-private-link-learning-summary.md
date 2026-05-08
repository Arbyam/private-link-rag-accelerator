# Azure Private Link Learning Summary

## What This Taught You

You've just learned one of the **most critical networking patterns in Azure**: how to securely access PaaS services without exposing them to the public internet. This is foundational knowledge for:

- **Enterprise cloud architecture** - Most organizations require private-only access to data stores
- **Zero Trust security** - Eliminating public endpoints is a core Zero Trust principle
- **Hybrid connectivity** - This same pattern extends to on-premises via VPN/ExpressRoute
- **Compliance** - Many regulations (HIPAA, PCI-DSS, SOC2) require private network access to sensitive data

### The Bigger Picture

In real-world Azure deployments, you'll rarely expose PaaS services publicly. Instead, you'll:

1. Deploy applications in VNets (App Service with VNet Integration, AKS, VMs)
2. Create Private Endpoints for all PaaS dependencies (Storage, SQL, Key Vault, etc.)
3. Disable public access on those PaaS services
4. Use Private DNS Zones to resolve FQDNs to private IPs

This pattern scales to **Hub-Spoke architectures** where a central hub VNet hosts shared Private DNS Zones, and spoke VNets peer to the hub for DNS resolution.

---

## Architecture You Built

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              Azure (East US)                                │
│                                                                             │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │                    Virtual Network: vnet-privatelink                   │ │
│  │                         Address Space: 10.0.0.0/16                     │ │
│  │                                                                        │ │
│  │   ┌──────────────────────┐      ┌────────────────────────────────┐     │ │
│  │   │  Subnet: snet-vm     │      │ Subnet: snet-privateendpoint   │     │ │
│  │   │  Range: 10.0.1.0/24  │      │ Range: 10.0.2.0/24             │     │ │
│  │   │                      │      │                                │     │ │
│  │   │  ┌────────────────┐  │      │  ┌──────────────────────────┐  │     │ │
│  │   │  │   vm-test      │  │      │  │  pe-storage-blob         │  │     │ │
│  │   │  │  10.0.1.4      │──┼──────┼─►│  10.0.2.4                 │  │     │ │
│  │   │  │                │  │      │  │  (Private Endpoint NIC)  │  │     │ │
│  │   │  └────────────────┘  │      │  └───────────┬──────────────┘  │     │ │
│  │   └──────────────────────┘      └──────────────┼─────────────────┘     │ │
│  │                                                │                       │ │
│  └────────────────────────────────────────────────┼───────────────────────┘ │
│                                                   │                         │
│  ┌────────────────────────────────────────────────┼───────────────────────┐ │
│  │          Private DNS Zone: privatelink.blob.core.windows.net           │ │
│  │                                                │                       │ │
│  │   A Record: stprivatelinklab2247 ──────────────┘                       │ │
│  │             Resolves to: 10.0.2.4                                      │ │
│  │                                                                        │ │
│  │   VNet Link: vnet-privatelink (auto-registration: disabled)            │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                   │                         │
│                                                   ▼                         │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │                 Storage Account: stprivatelinklab2247                  │ │
│  │                                                                        │ │
│  │   Blob Endpoint: https://stprivatelinklab2247.blob.core.windows.net    │ │
│  │   Public Access: DISABLED                                              │ │
│  │   Container: testcontainer                                             │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘

        ┌─────────────────┐
        │  Your Local PC  │
        │  (Internet)     │
        │                 │
        │  nslookup:      │───────► 57.150.245.225 (Public IP)
        │                 │         ❌ ACCESS BLOCKED
        └─────────────────┘
```

---

## Key Components Explained

### 1. Private Endpoint (`pe-storage-blob`)
**What it is:** A network interface (NIC) in YOUR VNet that represents the Azure PaaS service.

**Key details:**
- Gets a private IP from your subnet (10.0.2.4)
- Maps to a specific sub-resource (in this case, `blob`)
- Connection status must be "Approved" to work

**Why it matters:** This is the "entry point" into the PaaS service from your private network. Traffic never leaves the Microsoft backbone.

---

### 2. Private DNS Zone (`privatelink.blob.core.windows.net`)
**What it is:** A DNS zone that overrides public DNS resolution for the privatelink subdomain.

**Key details:**
- Name follows pattern: `privatelink.<service>.core.windows.net`
- Contains A record: `stprivatelinklab2247` → `10.0.2.4`
- Must be linked to your VNet to work

**Why it matters:** Without this, your VM would resolve the storage FQDN to the public IP and traffic would try to go over the internet (and fail, since public access is disabled).

---

### 3. VNet Link
**What it is:** Associates the Private DNS Zone with your Virtual Network.

**Key details:**
- Enables DNS queries from the VNet to use the Private DNS Zone
- Auto-registration is optional (not needed for Private Endpoints)

**Why it matters:** This is what makes `nslookup` return `10.0.2.4` instead of the public IP when run from inside the VNet.

---

### 4. Storage Account Network Settings
**What it is:** Controls whether the storage account accepts connections from public internet.

**Key details:**
- "Disabled" = only Private Endpoints can connect
- "Enabled from selected networks" = whitelist specific IPs/VNets
- "Enabled from all networks" = fully public

**Why it matters:** Disabling public access is the final step to ensure data can ONLY be accessed through your private network.

---

## Important IPs and Resources

| Resource | Name | IP/Value | Purpose |
|----------|------|----------|---------|
| Virtual Network | `vnet-privatelink` | `10.0.0.0/16` | Contains all resources |
| VM Subnet | `snet-vm` | `10.0.1.0/24` | Hosts test VM |
| PE Subnet | `snet-privateendpoint` | `10.0.2.0/24` | Hosts private endpoint NIC |
| Test VM | `vm-test` | `10.0.1.4` (private) / `20.51.225.87` (public) | Used to test private connectivity |
| Private Endpoint | `pe-storage-blob` | `10.0.2.4` | Entry point to storage |
| Storage Account | `stprivatelinklab2247` | N/A | Target PaaS service |
| Storage Blob FQDN | - | `stprivatelinklab2247.blob.core.windows.net` | What applications connect to |
| Private DNS Zone | `privatelink.blob.core.windows.net` | Global | Resolves FQDN to private IP |

---

## What To Look Out For

### Common Pitfalls

1. **DNS Resolution Issues**
   - Symptom: `nslookup` returns public IP instead of private
   - Cause: VNet not linked to Private DNS Zone, or wrong DNS zone name
   - Fix: Verify VNet link exists in the Private DNS Zone

2. **Connection Timeouts from VM**
   - Symptom: VM can't reach storage at all
   - Cause: NSG blocking traffic, or Private Endpoint not approved
   - Fix: Check Private Endpoint connection status = "Approved", verify NSGs

3. **"Public access not permitted" from VM**
   - Symptom: VM gets XML error about authentication
   - Cause: This is NORMAL - means network works, just needs auth
   - Note: This is different from "blocked by firewall" errors

4. **Wrong Subnet for Private Endpoint**
   - Best Practice: Use a dedicated subnet for Private Endpoints
   - Reason: Easier NSG management, clearer network topology

5. **Forgetting to Disable Public Access**
   - Risk: Data still accessible from internet even with Private Endpoint
   - Fix: Always disable public access after Private Endpoint is working

### DNS Zone Naming Convention

Each Azure service has its own Private DNS Zone name:

| Service | Private DNS Zone Name |
|---------|----------------------|
| Blob Storage | `privatelink.blob.core.windows.net` |
| Azure SQL | `privatelink.database.windows.net` |
| Key Vault | `privatelink.vaultcore.azure.net` |
| Azure Files | `privatelink.file.core.windows.net` |
| Cosmos DB | `privatelink.documents.azure.com` |

---

## How It All Ties Together

### The Flow (Step by Step)

1. **Application requests data:**
   ```
   curl https://stprivatelinklab2247.blob.core.windows.net/testcontainer/myfile.txt
   ```

2. **DNS Resolution (inside VNet):**
   - VM asks: "What's the IP for stprivatelinklab2247.blob.core.windows.net?"
   - Azure DNS checks Private DNS Zone (linked to VNet)
   - Finds A record: `stprivatelinklab2247` → `10.0.2.4`
   - Returns: `10.0.2.4`

3. **Network Path:**
   - VM (10.0.1.4) → Private Endpoint NIC (10.0.2.4) → Azure Storage (backend)
   - Traffic stays on Microsoft backbone, never touches public internet

4. **Response:**
   - Storage returns data through same private path
   - Application receives response

### The Magic: CNAME Chain

When you query the storage FQDN, you actually see:
```
stprivatelinklab2247.blob.core.windows.net
    → CNAME → stprivatelinklab2247.privatelink.blob.core.windows.net
        → A Record → 10.0.2.4 (from your Private DNS Zone)
```

Azure automatically adds the `privatelink` CNAME when you create a Private Endpoint. Your Private DNS Zone intercepts the `privatelink.*` query and returns the private IP.

---

## Next Steps to Deepen Your Knowledge

1. **Project 2:** Add Azure SQL Database with Private Endpoint (same pattern)
2. **Project 3:** Create Hub-Spoke with centralized Private DNS Zones
3. **Explore:** Use Azure Policy to enforce Private Endpoints on all PaaS
4. **Advanced:** Connect on-premises network and configure DNS forwarding

---

## Cleanup

When you're done, delete the resource group to remove all resources:

```bash
az group delete --name rg-private-link-lab --yes --no-wait
```

Or in Portal: Resource Groups → `rg-private-link-lab` → Delete resource group

---

## Quick Reference Commands

**Test DNS resolution (from VM):**
```bash
nslookup stprivatelinklab2247.blob.core.windows.net
```

**Test connectivity (from VM):**
```bash
curl -I https://stprivatelinklab2247.blob.core.windows.net
```

**SSH to test VM:**
```bash
ssh azureuser@20.51.225.87
```

---

*Document created: February 3, 2026*
*Lab completed successfully ✅*
