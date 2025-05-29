import re
from typing import Dict, List, Set
from datetime import datetime, timedelta


class ImprovedPrStat:
    """Enhanced PR scoring with reduced bias and better signals."""

    # Base scoring weights
    REVIEW_VALUE = 3.0
    COMMENT_VALUE = 1.0
    REACTION_VALUE = 0.3

    # Change type multipliers
    FEATURE_MULTIPLIER = 1.2
    BUGFIX_MULTIPLIER = 1.1
    SECURITY_MULTIPLIER = 2.5
    BREAKING_MULTIPLIER = 1.8
    DOCS_MULTIPLIER = 0.7
    TEST_MULTIPLIER = 0.8

    # Quality indicators
    DELETION_BONUS_THRESHOLD = 0.3  # >30% deletions = cleanup bonus
    CORE_FILES_BONUS = 1.3

    def __init__(self, pr_data: Dict, issue_data: Dict = None):
        self.pr_data = pr_data
        self.issue_data = issue_data or {}

        # Basic info
        self.number = pr_data["number"]
        self.title = pr_data["title"].lower()
        self.body = (pr_data.get("body", "") or "").lower()
        self.labels = [label.get("name", "").lower() for label in pr_data.get("labels", {}).get("nodes", [])]

        # Change metrics
        self.additions = pr_data.get("additions", 0)
        self.deletions = pr_data.get("deletions", 0)
        self.changed_files = pr_data.get("changedFiles", 1)

        # Time metrics
        self.created_at = pr_data.get("createdAt")
        self.merged_at = pr_data.get("mergedAt")

        self._score = None

    @property
    def deletion_ratio(self) -> float:
        """Calculate ratio of deletions to total changes."""
        total_changes = self.additions + self.deletions
        return self.deletions / max(total_changes, 1)

    @property
    def change_type_score(self) -> float:
        """Determine PR type and apply appropriate multiplier."""
        title_body = f"{self.title} {self.body}"

        # Security fixes get highest priority
        security_indicators = ["security", "cve", "vulnerability", "exploit", "xss", "injection"]
        if any(indicator in title_body for indicator in security_indicators):
            return self.SECURITY_MULTIPLIER

        # Breaking changes
        breaking_indicators = ["breaking", "breaking change", "api change", "deprecat"]
        if any(indicator in title_body for indicator in breaking_indicators):
            return self.BREAKING_MULTIPLIER

        # Features vs bugs vs docs
        if any(word in title_body for word in ["fix", "bug", "error", "issue"]):
            return self.BUGFIX_MULTIPLIER
        elif any(word in title_body for word in ["add", "feature", "implement", "support"]):
            return self.FEATURE_MULTIPLIER
        elif any(word in title_body for word in ["doc", "readme", "comment"]):
            return self.DOCS_MULTIPLIER
        elif "test" in title_body:
            return self.TEST_MULTIPLIER

        return 1.0

    @property
    def label_score(self) -> float:
        """Improved label scoring with more nuance."""
        score = 1.0

        # Critical labels get big boosts
        if any(label in self.labels for label in ["security", "critical", "blocker"]):
            score *= 2.0
        elif any(label in self.labels for label in ["urgent", "high-priority"]):
            score *= 1.5

        # Provider penalty is smaller and more targeted
        provider_labels = [label for label in self.labels if "provider" in label]
        if provider_labels:
            # Less harsh penalty, and only for certain provider types
            if any("amazon" in label or "google" in label for label in provider_labels):
                score *= 0.9  # Major providers get smaller penalty
            else:
                score *= 0.85  # Minor providers get slightly larger penalty

        return score

    @property
    def quality_score(self) -> float:
        """Score based on change quality indicators."""
        score = 1.0

        # Deletion bonus (cleanup/refactoring is valuable)
        if self.deletion_ratio > self.DELETION_BONUS_THRESHOLD:
            score *= 1.2

        # File count scoring (more nuanced)
        if self.changed_files > 50:
            score *= 0.7  # Very large changes need extra scrutiny
        elif self.changed_files > 20:
            score *= 0.85
        elif self.changed_files < 3:
            score *= 1.1  # Focused changes are good

        # Lines per file ratio
        lines_per_file = (self.additions + self.deletions) / max(self.changed_files, 1)
        if lines_per_file > 100:
            score *= 0.9  # Large changes per file might be less focused
        elif lines_per_file < 10:
            score *= 1.1  # Small, targeted changes

        return score

    @property
    def engagement_score(self) -> float:
        """Calculate engagement quality (not just quantity)."""
        # Base interaction counting (simplified from original)
        comments = len(self.pr_data.get("comments", {}).get("nodes", []))
        reviews = len(self.pr_data.get("reviews", {}).get("nodes", []))
        conv_comments = len(self.pr_data.get("timelineItems", {}).get("nodes", []))

        # Count unique participants
        participants = set()
        for comment in self.pr_data.get("comments", {}).get("nodes", []):
            if comment.get("author", {}).get("login"):
                participants.add(comment["author"]["login"])

        for review in self.pr_data.get("reviews", {}).get("nodes", []):
            if review.get("author", {}).get("login"):
                participants.add(review["author"]["login"])

        # Quality over quantity
        base_score = (
            reviews * self.REVIEW_VALUE +
            comments * self.COMMENT_VALUE +
            conv_comments * self.COMMENT_VALUE
        )

        # Participant diversity bonus
        if len(participants) > 5:
            base_score *= 1.3
        elif len(participants) > 3:
            base_score *= 1.15
        elif len(participants) < 2:
            base_score *= 0.8

        return max(base_score, 1.0)

    @property
    def urgency_score(self) -> float:
        """Score based on merge timeline."""
        if not self.created_at or not self.merged_at:
            return 1.0

        try:
            created = datetime.fromisoformat(self.created_at.replace('Z', '+00:00'))
            merged = datetime.fromisoformat(self.merged_at.replace('Z', '+00:00'))
            merge_time = merged - created

            # Very fast merges might indicate urgency
            if merge_time < timedelta(hours=2):
                return 1.4  # Hotfix territory
            elif merge_time < timedelta(hours=12):
                return 1.2  # Same day merge
            elif merge_time > timedelta(days=30):
                return 0.9  # Long-running PRs might be less critical

        except (ValueError, AttributeError):
            pass

        return 1.0

    @property
    def protm_multiplier(self) -> float:
        """Enhanced protm detection across all content."""
        protm_found = False

        # Check title and body
        if "protm" in f"{self.title} {self.body}":
            protm_found = True

        # Check all comments (would need to be implemented in data fetching)
        # This is a placeholder - the actual implementation would check all comment bodies

        return 15.0 if protm_found else 1.0  # Reduced from 20x to 15x

    @property
    def score(self) -> float:
        """Calculate comprehensive score."""
        if self._score is not None:
            return self._score

        self._score = (
            self.engagement_score *
            self.label_score *
            self.change_type_score *
            self.quality_score *
            self.urgency_score *
            self.protm_multiplier
        )

        return round(self._score, 3)

    def get_score_breakdown(self) -> Dict[str, float]:
        """Get detailed breakdown of scoring components."""
        return {
            "engagement": self.engagement_score,
            "labels": self.label_score,
            "change_type": self.change_type_score,
            "quality": self.quality_score,
            "urgency": self.urgency_score,
            "protm": self.protm_multiplier,
            "final": self.score
        }
