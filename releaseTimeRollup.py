import argparse
import epicTimeRollup
from dataclasses import dataclass, asdict
import os
import shutil
from jira import JIRA
from subprocess import Popen


@dataclass
class Release:
    release: str
    issues: []
    summed_time: float


def parse_args(args_list):
    """
    Parse arguments for release-time-rollup.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--user", required=True)
    parser.add_argument("--api_token", required=True)
    parser.add_argument("--releases", required=True)
    parser.add_argument("--export_estimates", action='store_true')
    parser.add_argument("--export_estimates_path")
    parser.add_argument("--export_project_configs", action='store_true')
    parser.add_argument("--export_project_config_path")
    parser.add_argument("--import_project_configs", action='store_true')
    parser.add_argument("--import_project_configs_path")

    args = parser.parse_args(args=args_list)

    return args


def execute(args_list):
    args = parse_args(args_list)
    print("Running JIRA Tabulations for Initiatives")
    jira_options = {"server": "https://battlefy.atlassian.net"}
    jira = JIRA(
        options=jira_options,
        basic_auth=(args.user, args.api_token),
    )

    releases = args.releases.split(",")
    project_configs = {}

    for release in releases:
        query_string = "fixVersion={}".format(release)
        # get a list of the issues first, just by summary and comprehend the
        # projects
        issue_projects = list(set([e.fields.project.id for e in jira.search_issues(
            query_string)]))

        if len(issue_projects) != 1:
            print("Multiple projects in release; unable to assert size.")
            return -1
        root_project_id = issue_projects[0]

        if root_project_id not in project_configs:
            project_configs[root_project_id] = epicTimeRollup.generate_project_constants(
                jira, jira.project(root_project_id))

        cust_keys = list(set([project_configs[root_project_id].story.estimation_key,
                              project_configs[root_project_id].task.estimation_key]))
        cust_key_str = ",".join(cust_keys)

        full_issues = jira.search_issues(
            query_string, fields="{}, subtasks, summary, issuetype".format(cust_key_str))

        for issue in full_issues:
