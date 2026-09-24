# Container orchestration

## Reader questions

- What problem does this code solve, and who has that problem?
- Who are the intended users, and what do they already know?
- What job does the user need to accomplish with this code, feature, or tool?
- What should the user be able to do after reading the documentation?
- What does the code or feature do, and what does it explicitly not do?
- What is the shortest realistic example that shows the code or feature being used successfully?
- What are the main concepts, components, commands, or workflows the user needs to understand?

Container orchestration coordinates containerized workloads across a group of machines. It manages where workloads run and keeps their actual state aligned with the state that an administrator specifies.

## How orchestration works

An orchestration platform separates cluster management from workload execution. A control plane accepts workload definitions, selects suitable machines, and monitors cluster state. Worker nodes run the containers assigned to them.

The platform commonly coordinates:

- Workload scheduling and lifecycle management
- Network connectivity and load balancing
- Persistent storage
- Scaling and recovery

## Core components

### Control plane

The control plane exposes the cluster API, stores cluster state, schedules workloads, and reconciles the running cluster with its declared configuration.

### Worker nodes

Worker nodes provide compute resources. Each node runs an agent that receives workload assignments and a container runtime that starts and stops containers.

## Example workload

The following workload definition requests three instances of an application:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: web
spec:
  replicas: 3
```

## Benefits

Orchestration gives teams a consistent way to deploy, scale, update, and recover applications without managing each machine independently.
