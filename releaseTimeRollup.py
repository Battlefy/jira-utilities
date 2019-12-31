import argparse
import epicTimeRollup
from dataclasses import dataclass, asdict
import os
import shutil
from jira import JIRA
import json
from subprocess import Popen


@dataclass
class Release:
    release: str
    issues: []
    summed_time: float

    def dict(self):
        issues_json = []
        est_count = 0

        for issue in self.issues:
            di = issue.dict()
            issues_json.append(issue.dict())
            if issue.summed_time > 0.0:
                est_count += 1
        return {'key': self.release.replace(" ", "_"), 'time': self.summed_time, 'subticket_count': len(self.issues), 'subticket_estimate_count': est_count, 'issues': issues_json}


def export_releases_json(root, releases_container):
    """
        file - fully qualified path to file in which to write to.
        releasess_container - the list of release DataObjects to export as JSON.
    """
    releases_json = {}
    for release_container in releases_container:
        if release_container.release not in releases_json:
            releases_json[release_container.release] = []

        print("Processing to JSON structure of {}".format(
            release_container.release))

        releases_json[release_container.release].append(
            release_container.dict())

    for release_key in releases_json:
        out_file_path = os.path.join(
            root, "{}_estimates.json".format(release_key.replace(" ", "_")))

        with open(out_file_path, "w") as output_file:
            output_file.writelines(json.dumps(
                releases_json[release_key], indent=4, separators=(",", ": ")))

    print("Finished writing to file.")


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
    print("Running JIRA Tabulations for Releases")
    jira_options = {"server": "https://battlefy.atlassian.net"}
    jira = JIRA(
        options=jira_options,
        basic_auth=(args.user, args.api_token),
    )

    releases = args.releases.split(",")
    releases_container = []
    project_configs = {}

    for release in releases:
        release_obj = Release(release, [], 0.0)
        releases_container.append(release_obj)
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

        release_obj.issues = [epicTimeRollup.UserStory(
            e, e.fields.subtasks if hasattr(
                e.fields, "subtasks") else [], 0.0
        )
            for e in jira.search_issues(
            query_string, fields="{}, subtasks, summary, issuetype".format(cust_key_str))
        ]

        for release in releases_container:
            for issue in release.issues:
                epicTimeRollup.extract_issue_estimate(
                    jira, issue, project_configs[root_project_id])
                release.summed_time += issue.summed_time

        if args.export_estimates:
            export_releases_json(
                args.export_estimates_path, releases_container)
