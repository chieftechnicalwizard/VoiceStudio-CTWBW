from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "mac-app-store.yml"


def load_workflow():
    return yaml.load(WORKFLOW.read_text(), Loader=yaml.BaseLoader)


def test_workflow_is_manual_private_and_distribution_scoped():
    workflow = load_workflow()
    assert set(workflow["on"]) == {"workflow_dispatch"}
    assert workflow["permissions"] == {"contents": "read"}
    assert workflow["env"]["VOICESTUDIO_DISTRIBUTION"] == "mac-app-store"
    source = WORKFLOW.read_text()
    assert "--publish never" in source
    assert "altool" not in source
    assert "notarytool" not in source
    assert "Transporter" not in source


def test_workflow_enforces_compliance_signing_and_provenance():
    workflow = load_workflow()
    validate = workflow["jobs"]["validate"]["steps"][-1]
    assert "--distribution=mac-app-store" in validate["run"]
    package = workflow["jobs"]["package"]
    names = [step.get("name") for step in package["steps"]]
    assert "Prepare App Store signing inputs" in names
    assert "Verify Apple Distribution signatures and sandbox" in names
    assert "Record artifact provenance" in names
    assert "Save private App Store handoff" in names
    build = next(step for step in package["steps"] if step.get("name") == "Build signed sandbox packages")
    assert set(build["env"]) == {
        "CSC_LINK",
        "CSC_KEY_PASSWORD",
        "CSC_INSTALLER_LINK",
        "CSC_INSTALLER_KEY_PASSWORD",
    }
