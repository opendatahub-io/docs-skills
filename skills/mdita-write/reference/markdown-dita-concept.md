---
$schema: urn:oasis:names:tc:dita:xsd:concept.xsd
id: about-container-orchestration
author: Documentation Team
category: Infrastructure
keyword:
  - containers
  - orchestration
  - kubernetes
---
# About container orchestration

Container orchestration is the automated management of containerized application deployment, scaling, networking, and lifecycle across clusters of machines.

## Architecture overview

A container orchestration platform uses a control plane and worker node architecture. The control plane manages the overall cluster state and makes scheduling decisions, while worker nodes execute application workloads in containers.

The orchestration system coordinates:

- Container lifecycle management across multiple machines
- Resource allocation and load balancing for applications
- Network connectivity between containers and services
- Storage provisioning and mounting for persistent data

### Control plane components

The control plane includes the following key components:

- **API server** — the central management point for the cluster that receives and processes all cluster operations
- **Scheduler** — assigns workloads to appropriate worker nodes based on resource requirements and constraints
- **Controller manager** — runs controllers that monitor cluster state and automatically remediate deviations from desired state
- **State store** — a distributed database that persists all cluster configuration and state

### Worker nodes

Worker nodes run the container runtime and host application pods. Each worker node includes:

Kubelet
:   The primary node agent that monitors and manages container lifecycle on the node.

Container runtime
:   The software responsible for pulling images and running containers.

Network proxy
:   Maintains routing rules and network load balancing for container traffic.

## Supported platforms

Container orchestration can be deployed on various infrastructure providers:

| Provider | Architecture | Notes |
|----------|-------------|-------|
| AWS | x86_64, aarch64 | Includes managed service options |
| Azure | x86_64 | Includes managed and self-managed deployments |
| GCP | x86_64 | Supports both self-managed and managed platforms |
| Bare metal | x86_64, aarch64 | Requires manual infrastructure provisioning |

!!! note
    Most platforms support multiple architectures and offer both managed and self-managed deployment options. Consult your provider documentation for specific support matrices.

## Key benefits

Container orchestration provides the following benefits for production environments:

1. Automatic scaling and load distribution across clusters
2. Self-healing with automatic container restart and rescheduling
3. Rolling updates and rollback capabilities for zero-downtime deployments
4. Unified resource management and multi-cluster capabilities

> Infrastructure abstraction through orchestration enables teams to focus on application development rather than machine-level operations and configuration management.
