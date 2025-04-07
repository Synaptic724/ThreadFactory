# Security Policy

## Overview

**ThreadFactory** is a backend concurrency framework.  
It does not open network ports, manage user data, or expose any remote interfaces.

While the risk of external attack is minimal due to its offline nature, **we take security seriously** — particularly in the areas of:

- Safe thread lifecycle management
- Predictable execution flow
- Memory integrity and state isolation

---

## Supported Versions

Below are the officially supported versions with regard to security-related updates and patches:

| Version | Security Support      |
| ------- | --------------------- |
| 1.2.x   | ✅ Actively supported |
| 1.1.x   | ⚠️ Best effort        |
| 1.0.x   | ❌ Unsupported         |

- ✅ Active support: security issues will be investigated and patched as appropriate.
- ⚠️ Best effort: no guarantee, but critical issues may receive patches.
- ❌ Unsupported: no updates provided.

---

## Reporting a Vulnerability

If you discover a security issue — such as a condition that could cause unsafe execution, thread abuse, or a system hang — please report it via:

📧 **SynapticAISystems@hotmail.com**

Please include:
- A clear description of the issue
- Steps to reproduce
- Environment details (OS, Python version, workload size)
- Any logs or crash traces, if available

We will assess the report, classify severity, and provide a fix or mitigation if appropriate.

---

We appreciate all responsible disclosures and strive to maintain a secure and predictable foundation for concurrent Python execution.
