"""Join published Analysis Memory history and the warehouse migration chain.

Previously published revisions remain immutable. Historical analysis state and
canary records are retained even though their former runtime paths are retired.
"""

revision = "20261012_0014"
down_revision = ("20261010_0013", "20260728_0005")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
