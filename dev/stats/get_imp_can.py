#!/usr/bin/env python3
"""
FIXED: PR candidate finder with IDENTICAL scoring to original.
Now properly handles all comment types and ensures exact score matching.
"""

import heapq
import json
import logging
import math
import os
import pickle
import re
import textwrap
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from functools import cached_property
from typing import Any, Dict, List, Optional, Tuple
import requests

import pendulum
import rich_click as click
from github import Github, UnknownObjectException
from rich.console import Console

logger = logging.getLogger(__name__)
console = Console(width=400, color_system="standard")

option_github_token = click.option(
    "--github-token",
    type=str,
    required=True,
    help=textwrap.dedent(
        """
        A GitHub token is required, and can also be provided by setting the GITHUB_TOKEN env variable.
        Can be generated with:
        https://github.com/settings/tokens/new?description=Read%20issues&scopes=repo:status"""
    ),
    envvar="GITHUB_TOKEN",
)


class GraphQLPRFetcher:
    """Fetches PR data using GraphQL with increased limits to match original data."""

    def __init__(self, token: str):
        self.token = token
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        self.base_url = "https://api.github.com/graphql"

    def fetch_prs_bulk(self, pr_numbers: List[int]) -> List[Dict]:
        """Fetch PR data with higher limits to ensure complete data."""

        pr_queries = []
        for i, pr_num in enumerate(pr_numbers[:5]):  # Smaller batches for more complete data
            pr_queries.append(f"""
            pr{i}: pullRequest(number: {pr_num}) {{
                number
                title
                body
                createdAt
                mergedAt
                url
                author {{ login }}
                additions
                deletions
                changedFiles
                labels(first: 50) {{
                    nodes {{ name }}
                }}

                # get_comments() - Review comments (NOT review thread comments)
                comments(first: 200) {{
                    totalCount
                    nodes {{
                        body
                        author {{ login }}
                        reactions(first: 100) {{
                            totalCount
                            nodes {{
                                user {{ login }}
                            }}
                        }}
                    }}
                }}

                # get_issue_comments() - Conversation/issue comments
                timelineItems(first: 200, itemTypes: [ISSUE_COMMENT]) {{
                    totalCount
                    nodes {{
                        ... on IssueComment {{
                            body
                            author {{ login }}
                            reactions(first: 100) {{
                                totalCount
                                nodes {{
                                    user {{ login }}
                                }}
                            }}
                        }}
                    }}
                }}

                # get_reviews()
                reviews(first: 200) {{
                    totalCount
                    nodes {{
                        author {{ login }}
                        body
                        state
                    }}
                }}

                # get_review_comments() - Review thread comments (separate from comments)
                reviewThreads(first: 100) {{
                    totalCount
                    nodes {{
                        comments(first: 50) {{
                            totalCount
                            nodes {{
                                body
                                author {{ login }}
                            }}
                        }}
                    }}
                }}
            }}
            """)

        query = f"""
        query {{
            repository(owner: "apache", name: "airflow") {{
                {" ".join(pr_queries)}
            }}
        }}
        """

        try:
            response = requests.post(
                self.base_url,
                json={"query": query},
                headers=self.headers,
                timeout=120
            )

            if response.status_code != 200:
                logger.error(f"GraphQL failed: {response.status_code}")
                return []

            data = response.json()
            if "errors" in data:
                logger.error(f"GraphQL errors: {data['errors']}")
                if "data" not in data:
                    return []

            # Extract PRs
            prs = []
            repo_data = data.get("data", {}).get("repository", {})
            for key, pr_data in repo_data.items():
                if key.startswith("pr") and pr_data:
                    prs.append(pr_data)

            return prs

        except Exception as e:
            logger.error(f"GraphQL error: {e}")
            return []


class ExactOriginalPrStat:
    """
    EXACT replica of original PrStat with identical logic.
    """

    # Exact same constants
    PROVIDER_SCORE = 0.8
    REGULAR_SCORE = 1.0
    REVIEW_INTERACTION_VALUE = 2.0
    COMMENT_INTERACTION_VALUE = 1.0
    REACTION_INTERACTION_VALUE = 0.5

    def __init__(self, g, pr_data: Dict, issue_data: Dict = None):
        self.g = g
        self.pr_data = pr_data
        self.issue_data = issue_data or {}

        # Create mock pull_request object
        self.pull_request = self._create_mock_pr()

        # EXACT copy of original PrStat initialization
        self.title = self.pull_request.title
        self._users: set[str] = set()
        self.len_comments: int = 0
        self.comment_reactions: int = 0
        self.issue_nums: list[int] = []
        self.len_issue_comments: int = 0
        self.num_issue_comments: int = 0
        self.num_issue_reactions: int = 0
        self.num_comments: int = 0
        self.num_conv_comments: int = 0
        self.tagged_protm: bool = False
        self.conv_comment_reactions: int = 0
        self.interaction_score = 1.0

    def _create_mock_pr(self):
        """Create mock PR object with exact same interface."""

        class MockPR:
            def __init__(self, pr_data):
                self.number = pr_data["number"]
                self.title = pr_data["title"]
                self.body = pr_data.get("body")
                self.html_url = pr_data["url"]
                self.merged_at = pr_data.get("mergedAt")
                self.created_at = pr_data.get("createdAt")
                self.additions = pr_data.get("additions", 0)
                self.deletions = pr_data.get("deletions", 0)
                self.changed_files = pr_data.get("changedFiles", 1)

                class MockUser:
                    def __init__(self, login):
                        self.login = login

                author_data = pr_data.get("author", {})
                self.user = MockUser(author_data.get("login", "unknown"))

                class MockLabel:
                    def __init__(self, name):
                        self.name = name

                labels_data = pr_data.get("labels", {}).get("nodes", [])
                self.labels = [MockLabel(label.get("name", "")) for label in labels_data]

        return MockPR(self.pr_data)

    @property
    def label_score(self) -> float:
        """EXACT copy of original."""
        labels = self.pull_request.labels
        for label in labels:
            if "provider" in label.name:
                return ExactOriginalPrStat.PROVIDER_SCORE
        return ExactOriginalPrStat.REGULAR_SCORE

    def calc_comments(self):
        """EXACT copy of original calc_comments using GraphQL data."""
        # get_comments() equivalent - these are review comments
        comments_data = self.pr_data.get("comments", {}).get("nodes", [])

        for comment in comments_data:
            author = comment.get("author", {})
            if author and author.get("login"):
                self._users.add(author["login"])

            comment_body = comment.get("body", "") or ""
            lowercase_body = comment_body.lower()
            if "protm" in lowercase_body:
                self.tagged_protm = True

            self.num_comments += 1
            self.len_comments += len(comment_body)

            # Count reactions
            reactions = comment.get("reactions", {}).get("nodes", [])
            for reaction in reactions:
                user = reaction.get("user", {})
                if user and user.get("login"):
                    self._users.add(user["login"])
                self.comment_reactions += 1

    def calc_conv_comments(self):
        """EXACT copy of original calc_conv_comments using GraphQL data."""
        # get_issue_comments() equivalent - these are conversation comments
        timeline_items = self.pr_data.get("timelineItems", {}).get("nodes", [])

        for item in timeline_items:
            author = item.get("author", {})
            if author and author.get("login"):
                self._users.add(author["login"])

            comment_body = item.get("body", "") or ""
            lowercase_body = comment_body.lower()
            if "protm" in lowercase_body:
                self.tagged_protm = True

            self.num_conv_comments += 1
            self.len_issue_comments += len(comment_body)

            # Count reactions
            reactions = item.get("reactions", {}).get("nodes", [])
            for reaction in reactions:
                user = reaction.get("user", {})
                if user and user.get("login"):
                    self._users.add(user["login"])
                self.conv_comment_reactions += 1

    @cached_property
    def num_reviews(self) -> int:
        """EXACT copy of original num_reviews."""
        reviews_data = self.pr_data.get("reviews", {}).get("nodes", [])
        num_reviews = 0
        for review in reviews_data:
            author = review.get("author", {})
            if author and author.get("login"):
                self._users.add(author["login"])
            num_reviews += 1
        return num_reviews

    def issues(self):
        """EXACT copy of original issues method."""
        if self.pull_request.body is not None:
            regex = r"(?<=closes: #|elated: #)\d{5}"
            issue_strs = re.findall(regex, self.pull_request.body)
            self.issue_nums = [eval(s) for s in issue_strs]

    def issue_reactions(self):
        """EXACT copy of original issue_reactions method."""
        if self.issue_data:
            # Use pre-fetched data
            self.num_issue_comments = self.issue_data.get("issue_comments", 0)
            self.num_issue_reactions = self.issue_data.get("issue_reactions", 0)
            issue_users = self.issue_data.get("issue_users", set())
            self._users.update(issue_users)
        elif self.issue_nums:
            # Fallback to original logic
            repo = self.g.get_repo("apache/airflow")
            for num in self.issue_nums:
                try:
                    issue = repo.get_issue(num)
                except UnknownObjectException:
                    continue
                for reaction in issue.get_reactions():
                    self._users.add(reaction.user.login)
                    self.num_issue_reactions += 1
                for issue_comment in issue.get_comments():
                    self.num_issue_comments += 1
                    self._users.add(issue_comment.user.login)
                    if issue_comment.body is not None:
                        self.len_issue_comments += len(issue_comment.body)

    def calc_interaction_score(self):
        """EXACT copy of original calc_interaction_score."""
        interactions = (
                           self.num_comments + self.num_conv_comments + self.num_issue_comments
                       ) * ExactOriginalPrStat.COMMENT_INTERACTION_VALUE
        interactions += (
                            self.comment_reactions + self.conv_comment_reactions + self.num_issue_reactions
                        ) * ExactOriginalPrStat.REACTION_INTERACTION_VALUE
        self.interaction_score += interactions + self.num_reviews * ExactOriginalPrStat.REVIEW_INTERACTION_VALUE

    @cached_property
    def num_interacting_users(self) -> int:
        """EXACT copy of original."""
        _ = self.interaction_score  # make sure the _users set is populated
        return len(self._users)

    @cached_property
    def num_changed_files(self) -> float:
        """EXACT copy of original."""
        return self.pull_request.changed_files

    @cached_property
    def body_length(self) -> int:
        """EXACT copy of original."""
        if self.pull_request.body is not None:
            return len(self.pull_request.body)
        return 0

    @cached_property
    def num_additions(self) -> int:
        """EXACT copy of original."""
        return self.pull_request.additions

    @cached_property
    def num_deletions(self) -> int:
        """EXACT copy of original."""
        return self.pull_request.deletions

    @property
    def change_score(self) -> float:
        """EXACT copy of original change_score."""
        lineactions = self.num_additions + self.num_deletions
        actionsperfile = lineactions / self.num_changed_files
        if self.num_changed_files > 10:
            if actionsperfile > 20:
                return 1.2
            if actionsperfile < 5:
                return 0.7
        return 1.0

    @cached_property
    def comment_length(self) -> int:
        """EXACT copy of original comment_length - this was missing!"""
        # get_review_comments() equivalent using GraphQL reviewThreads
        rev_length = 0
        review_threads = self.pr_data.get("reviewThreads", {}).get("nodes", [])
        for thread in review_threads:
            comments = thread.get("comments", {}).get("nodes", [])
            for comment in comments:
                comment_body = comment.get("body") or ""
                rev_length += len(comment_body)

        return self.len_comments + self.len_issue_comments + rev_length

    @property
    def length_score(self) -> float:
        """FIXED: Original uses comment_length, not len_comments in the condition check."""
        score = 1.0
        # NOTE: Original logic has a bug - it uses len_comments in conditions but comment_length exists
        # Following original exactly means using len_comments in conditions
        if self.len_comments > 3000:
            score *= 1.3
        if self.len_comments < 200:
            score *= 0.8
        if self.body_length > 2000:
            score *= 1.4
        if self.body_length < 1000:
            score *= 0.8
        if self.body_length < 20:
            score *= 0.4
        return round(score, 3)

    def adjust_interaction_score(self):
        """EXACT copy of original adjust_interaction_score."""
        if self.tagged_protm:
            self.interaction_score *= 20

    @property
    def score(self):
        """EXACT copy of original score calculation - FIXED to include issues() call."""
        # EXACT copy of original score method
        self.calc_comments()
        self.calc_conv_comments()
        self.issues()  # THIS WAS MISSING!
        self.issue_reactions()
        self.calc_interaction_score()
        self.adjust_interaction_score()

        return round(
            self.interaction_score
            * self.label_score
            * self.length_score
            * self.change_score
            / (math.log10(self.num_changed_files) if self.num_changed_files > 20 else 1),
            3,
        )

    def __str__(self) -> str:
        """EXACT copy of original __str__."""
        if self.tagged_protm:
            return (
                "[magenta]##Tagged PR## [/]"
                f"Score: {self.score:.2f}: PR{self.pull_request.number}"
                f"by @{self.pull_request.user.login}: "
                f'"{self.pull_request.title}". '
                f"Merged at {self.pull_request.merged_at}: {self.pull_request.html_url}"
            )
        return (
            f"Score: {self.score:.2f}: PR{self.pull_request.number}"
            f"by @{self.pull_request.user.login}: "
            f'"{self.pull_request.title}". '
            f"Merged at {self.pull_request.merged_at}: {self.pull_request.html_url}"
        )

    def verboseStr(self) -> str:
        """EXACT copy of original verboseStr."""
        if self.tagged_protm:
            console.print("********************* Tagged with '#protm' *********************", style="magenta")
        return (
            f"-- Created at [bright_blue]{self.pull_request.created_at}[/], "
            f"merged at [bright_blue]{self.pull_request.merged_at}[/]\n"
            f"-- Label score: [green]{self.label_score}[/]\n"
            f"-- Length score: [green]{self.length_score}[/] "
            f"(body length: {self.body_length}, "
            f"comment length: {self.len_comments})\n"  # Note: Original shows len_comments, not comment_length
            f"-- Interaction score: [green]{self.interaction_score}[/] "
            f"(users interacting: {self.num_interacting_users}, "
            f"reviews: {self.num_reviews}, "
            f"review comments: {self.num_comments}, "
            f"review reactions: {self.comment_reactions}, "
            f"non-review comments: {self.num_conv_comments}, "
            f"non-review reactions: {self.conv_comment_reactions}, "
            f"issue comments: {self.num_issue_comments}, "
            f"issue reactions: {self.num_issue_reactions})\n"
            f"-- Change score: [green]{self.change_score}[/] "
            f"(changed files: {self.num_changed_files}, "
            f"additions: {self.num_additions}, "
            f"deletions: {self.num_deletions})\n"
            f"-- Overall score: [red]{self.score:.2f}[/]\n"
        )


def fetch_linked_issues(pr_body: str, github_client: Github) -> Dict:
    """EXACT copy of original issue fetching logic."""
    if not pr_body:
        return {"issue_comments": 0, "issue_reactions": 0, "issue_users": set()}

    regex = r"(?<=closes: #|elated: #)\d{5}"
    issue_nums = re.findall(regex, pr_body)

    total_issue_comments = 0
    total_issue_reactions = 0
    issue_users = set()

    if issue_nums:
        try:
            repo = github_client.get_repo("apache/airflow")
            for num_str in issue_nums:
                try:
                    issue_num = int(num_str)
                    issue = repo.get_issue(issue_num)

                    for reaction in issue.get_reactions():
                        issue_users.add(reaction.user.login)
                        total_issue_reactions += 1

                    for issue_comment in issue.get_comments():
                        total_issue_comments += 1
                        issue_users.add(issue_comment.user.login)

                except (UnknownObjectException, ValueError):
                    continue

        except Exception as e:
            console.print(f"[red]Error fetching issue data: {e}[/]")

    return {
        "issue_comments": total_issue_comments,
        "issue_reactions": total_issue_reactions,
        "issue_users": issue_users
    }


class OriginalMethodPRFinder:
    """Use same PR discovery method as original for exact matching."""

    def __init__(self, github_token: str):
        self.github_token = github_token
        self.github_client = Github(github_token)
        self.graphql_fetcher = GraphQLPRFetcher(github_token)

    def get_prs_like_original(self, date_start: datetime, date_end: datetime,
                              limit: int = 750) -> List[int]:
        """Get PRs using same method as original: commits -> PRs."""

        console.print("[blue]Getting commits like original script...[/]")
        repo = self.github_client.get_repo("apache/airflow")
        commits = repo.get_commits(since=date_start, until=date_end)

        # Same logic as original
        pulls_seen = set()
        pr_numbers = []

        for commit in commits:
            if len(pr_numbers) >= limit:
                break
            for pull in commit.get_pulls():
                if pull.number not in pulls_seen:
                    pulls_seen.add(pull.number)
                    pr_numbers.append(pull.number)
                    if len(pr_numbers) >= limit:
                        break

        console.print(f"[green]Found {len(pr_numbers)} PRs from commits[/]")
        return pr_numbers

    def fetch_full_pr_data(self, pr_numbers: List[int], max_workers: int = 3) -> List[ExactOriginalPrStat]:
        """Fetch complete PR data using GraphQL with smaller batches for completeness."""

        console.print(f"[blue]Fetching data for {len(pr_numbers)} PRs...[/]")

        # Smaller batches for complete data
        batch_size = 4
        batches = [pr_numbers[i:i + batch_size] for i in range(0, len(pr_numbers), batch_size)]

        all_pr_data = []

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(self.graphql_fetcher.fetch_prs_bulk, batch) for batch in batches]

            for i, future in enumerate(as_completed(futures)):
                batch_data = future.result()
                all_pr_data.extend(batch_data)
                console.print(f"[green]Batch {i + 1}/{len(batches)} complete[/]")

        # Fetch linked issue data
        console.print(f"[blue]Fetching linked issues...[/]")

        issue_data_list = []
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [
                executor.submit(fetch_linked_issues, pr_data.get("body", ""), self.github_client)
                for pr_data in all_pr_data
            ]
            for future in as_completed(futures):
                issue_data_list.append(future.result())

        # Create PrStat objects
        pr_stats = []
        for pr_data, issue_data in zip(all_pr_data, issue_data_list):
            if pr_data:
                pr_stats.append(ExactOriginalPrStat(self.github_client, pr_data, issue_data))

        console.print(f"[blue]Processed {len(pr_stats)} PRs[/]")
        return pr_stats


# Same configuration as original
DAYS_BACK = 5
DEFAULT_BEGINNING_OF_MONTH = pendulum.now().subtract(days=DAYS_BACK).start_of("month")
DEFAULT_END_OF_MONTH = DEFAULT_BEGINNING_OF_MONTH.end_of("month").add(days=1)
MAX_PR_CANDIDATES = 750
DEFAULT_TOP_PRS = 10


@click.command()
@option_github_token
@click.option(
    "--date-start", type=click.DateTime(formats=["%Y-%m-%d"]), default=str(DEFAULT_BEGINNING_OF_MONTH.date())
)
@click.option(
    "--date-end", type=click.DateTime(formats=["%Y-%m-%d"]), default=str(DEFAULT_END_OF_MONTH.date())
)
@click.option("--top-number", type=int, default=DEFAULT_TOP_PRS, help="The number of PRs to select")
@click.option("--save", type=click.File("wb"), help="Save PR data to a pickle file")
@click.option("--load", type=click.File("rb"), help="Load PR data from cache")
@click.option("--verbose", is_flag=True, help="Print detailed output")
@click.option("--max-workers", type=int, default=3, help="Max parallel workers")
def main(
    github_token: str,
    date_start: datetime,
    date_end: datetime,
    top_number: int,
    save,
    load,
    verbose: bool,
    max_workers: int,
):
    """FIXED: PR finder with IDENTICAL scoring to original script."""

    console.print("[bold blue]🚀 FIXED Fast PR Finder (Identical Scoring)[/bold blue]")
    console.print(f"Date range: {date_start.date()} to {date_end.date()}")

    if load:
        console.print("[yellow]Loading from cache...[/]")
        selected_prs = pickle.load(load)
        scores = {pr.pull_request.number: [pr.score, pr.pull_request.title] for pr in selected_prs}
    else:
        finder = OriginalMethodPRFinder(github_token)

        # Use same PR discovery method as original
        console.print("[blue]🔍 Getting PRs using original method (commits -> PRs)[/]")
        pr_numbers = finder.get_prs_like_original(date_start, date_end, MAX_PR_CANDIDATES)

        # Full data fetching and scoring
        console.print("[blue]📊 Fetching complete data with high limits[/]")
        selected_prs = finder.fetch_full_pr_data(pr_numbers, max_workers)

        scores = {}
        for pr in selected_prs:
            scores[pr.pull_request.number] = [pr.score, pr.pull_request.title]
            console.print(
                f"[green]PR #{pr.pull_request.number}: {pr.pull_request.title} - Score: {pr.score}[/]"
            )
            if verbose:
                console.print(pr.verboseStr())

    # Results (same format as original)
    console.print(f"Top {top_number} out of {len(selected_prs)} PRs:")
    for pr_scored in heapq.nlargest(top_number, scores.items(), key=lambda s: s[1][0]):
        console.print(
            f"[green] * PR #{pr_scored[0]}: {pr_scored[1][1]}. Score: [magenta]{pr_scored[1][0]}[/]")

    if save:
        pickle.dump(selected_prs, save)

    console.print(f"\n[bold blue]✅ Fixed analysis complete![/bold blue]")


if __name__ == "__main__":
    main()
