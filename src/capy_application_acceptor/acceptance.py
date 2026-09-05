"""Muse-owned independent execution and portable evidence; frozen entrypoint."""
from pathlib import Path
from .models import Candidate, Evaluation, Profile


def evaluate(candidate: Candidate, profile: Profile, release: dict, work_root: Path) -> Evaluation:
    """Evaluate validated inputs in an empty owned root, leaving it empty on return.

    Tool/input failures raise AcceptorError. Semantic mismatches return REJECTED.
    No database, source checkout, Git or external service is available to this core.
    """
    raise NotImplementedError("Contributor implementation pending")
