# Milestone 6 synthetic GPU fixture for owner review

The [exact fixture](../tests/fixtures/training/train.json) is AI-drafted synthetic supervision,
not historical facts or independently verified safety guidance. It reuses the four advice texts
previously reviewed for the Milestone 1 spike and adds the current structured response fields.
Approval for this new workflow is recorded separately against the fixture's SHA-256 in
[review.json](../tests/fixtures/training/review.json). Pending review blocks the real smoke run.

Mission: advise on rental-tool use; require a current pre-use inspection and no reported damage.
Keep overdue or damaged tools out of use pending inspection. Ask for missing inspection or damage
status. Advise only; perform no action. All examples have empty citations and the limitation
“Synthetic demonstration; no independent inspection evidence.”

| Situation | Desired response | Structured supervision |
| --- | --- | --- |
| Drill: current inspection, no damage reported | “The drill can be used subject to normal operating checks.” Explanation: “The reported inspection is current and no damage is reported.” | recommend; no missing facts/question; supporting quote is the complete supplied situation |
| Sander: overdue inspection, no damage reported | “Keep the sander out of use pending inspection.” Explanation: “The reported pre-use inspection is overdue.” | recommend; no missing facts/question; supporting quote is the complete supplied situation |
| Saw: current inspection, damage status absent | “Wait for damage information before deciding.” Explanation: “Damage status is required and is missing.” Question: “Is any damage reported on the saw?” | clarify; missing damage status; no supporting quotes |
| Mixer: no damage reported, inspection status absent | “Wait for inspection information before deciding.” Explanation: “Inspection status is required and is missing.” Question: “Is the mixer pre-use inspection current or overdue?” | clarify; missing inspection status; no supporting quotes |

Two distinct reworded evaluation situations are frozen separately: a polisher with both required
facts (recommend) and a router missing inspection status (ask specifically about inspection).
Their targets/rubrics never enter trainer mounts or synthetic-generation prompts. They are a tiny
workflow check, not proof of generalization, causal lift or safe real-world recommendations.

The reviewed command is:

```sh
make test-gpu GPU_WORKFLOW=training GPU_MODE=wsl
```

This builds the pinned Trixie trainer/runtime images, reuses the existing verified base snapshot
and base GGUF, creates a disposable local project, approves only these hash-matched reviewed
synthetic examples, and runs one quick 12-step LoRA attempt. Training has a 20-minute hard limit,
conversion a separate 20-minute limit, and frozen CPU comparison a 20-minute limit. Containers
have 4 CPU, 10 GiB RAM and explicit GPU access only during preflight/training. It needs at least
12 GB free artifact disk plus Docker image space and a compatible NVIDIA GPU with at least 6 GB
VRAM. WSL mode uses the same explicit read-only driver mounts as the verified Milestone 1 spike.
Training, conversion and inference are offline. There is no cloud job, builder API call,
automatic retry or active-version promotion. No other projects are changed.
