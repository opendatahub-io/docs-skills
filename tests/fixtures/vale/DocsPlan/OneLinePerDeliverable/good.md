---
title: Mirror the release payload into a disconnected registry before the install begins
---

# Plan

- Create the installing guide covering prerequisites and the mirror registry setup

```bash
oc adm release mirror --from=quay.io/openshift-release-dev/ocp-release:4.19.0-x86_64 --to=registry.example.com/ocp4/openshift4
```
