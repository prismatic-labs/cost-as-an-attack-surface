# Security policy

This repository demonstrates a resource-consumption failure mode inside a local sandbox. It is not an attack tool and it does not target other people's systems.

## What is in scope

- A bug that lets notebook parameters or a policy exceed `SafetyCeilings`.
- A path in the package that opens a network connection.
- A guard check that records a violation only after the refused work has already run.
- A report that presents illustrative cost as a real charge.
- Dependency or supply-chain issues in this repository's own code.

## What is out of scope

- Using the workshop against a model account, a cloud account, or any system that is not yours.
- Requests for exploit steps, payloads, or target lists.
- Availability of Google Colab's free tier. That is Google's service policy.

The simulator has no URL field and no packet sender. Please do not add one. The injected instruction in the fictional notes is aimed at the classroom agent only.

## Reporting

Open a private security advisory at <https://github.com/prismatic-labs/cost-as-an-attack-surface/security/advisories/new>.

Include the file, the limit you were able to pass, and the smallest change that shows the problem. Please do not include credentials or data from a real system.

## Supported use

Run the package and the notebook as documented. The hard ceilings are part of the safety model, including when a policy is set to the sandbox maximum.
