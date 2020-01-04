import argparse
import epicTimeRollup
from dataclasses import dataclass, asdict
import os
import shutil
import json
from jira import JIRA
from subprocess import Popen


@dataclass
class Initiative:
    initiative: JIRA.issue
    epics: []
    summed_time: float
    remaining_time: float

    def dict(self):
        epic_json = []
        incomplete_unestimated_count = 0
        incomplete_estimated_count = 0
        for epic in self.epics:
            epic_json.append(epic.dict())
            incomplete_estimated_count += epic.incomplete_estimated_count
            incomplete_unestimated_count += epic.incomplete_unestimated_count

        return {'key': self.initiative.key, 'summary': self.initiative.fields.summary, 'summed_time': self.summed_time, 'remaining_time': self.remaining_time, 'incomplete_estimated_count': incomplete_estimated_count, 'incomplete_unestimated_count': incomplete_unestimated_count, 'epics': epic_json}


def export_initiatives_json(root, initiatives_container):
    """
        file - fully qualified path to file in which to write to.
        initiatives_container - the list of initiative DataObjects to export as JSON.
    """
    initaitives_json = {}
    for initiative_container in initiatives_container:
        if initiative_container.initiative.fields.project.key not in initaitives_json:
            initaitives_json[initiative_container.initiative.fields.project.key] = [
            ]

        print("Processing to JSON structure of {}".format(
            initiative_container.initiative.key))

        initaitives_json[initiative_container.initiative.fields.project.key].append(
            initiative_container.dict())

    for project_key in initaitives_json:
        out_file_path = os.path.join(
            root, "{}_estimates.json".format(project_key))

        with open(out_file_path, "w") as output_file:
            print("Writing file {}".format(out_file_path))
            output_file.writelines(json.dumps(
                initaitives_json[project_key], indent=4, separators=(",", ": ")))

    print("Finished writing to file.")


def parse_args(args_list):
    """
    Parse arguments for epic-time-rollup.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--user", required=True)
    parser.add_argument("--api_token", required=True)
    parser.add_argument("--initiatives", required=True)
    parser.add_argument("--update_ticket_estimates", action='store_true')
    parser.add_argument("--force_toplevel_recalculate", action='store_true')
    parser.add_argument("--export_estimates", action='store_true')
    parser.add_argument("--export_estimates_path")
    parser.add_argument("--export_project_configs", action='store_true')
    parser.add_argument("--export_project_config_path")
    parser.add_argument("--import_project_configs", action='store_true')
    parser.add_argument("--import_project_configs_path")

    args = parser.parse_args(args=args_list)

    return args


def create_epic_rollup_args(source_args, initiative, epics):
    epic_rollup_args = source_args.copy()

    idx = epic_rollup_args.index('--initiatives')

    if(idx > -1):
        del epic_rollup_args[idx]
        del epic_rollup_args[idx]
        epic_rollup_args.append('--epics')
        epic_rollup_args.append(','.join(epics))

    idx = epic_rollup_args.index("--export_estimates_path")

    if idx > -1:
        idx = idx+1
        epic_rollup_args[idx] = os.path.join(epic_rollup_args[idx], initiative)
        if os.path.exists(epic_rollup_args[idx]):
            shutil.rmtree(epic_rollup_args[idx])
        os.mkdir(epic_rollup_args[idx])

    return epic_rollup_args


def execute(args_list):
    args = parse_args(args_list)
    print("Running JIRA Tabulations for Initiatives")
    jira_options = {"server": "https://battlefy.atlassian.net"}
    jira = JIRA(
        options=jira_options,
        basic_auth=(args.user, args.api_token),
    )

    initiatives = args.initiatives.split(",")
    initiatives_container = []

    for initiative in initiatives:
        print("Obtaining roll-up for {}".format(initiative))
        initiative_issue = jira.issue(initiative)
        keys = [
            x.inwardIssue.key for x in initiative_issue.fields.issuelinks if 'FRONT' not in x.inwardIssue.key]

        new_args = create_epic_rollup_args(args_list, initiative, keys)
        epics_container = epicTimeRollup.execute(
            new_args) if len(keys) != 0 else []

        curr_initiative = Initiative(
            initiative_issue, epics_container, 0.0, 0.0)

        for epic in epics_container:
            curr_initiative.summed_time += epic.summed_time
            curr_initiative.remaining_time += epic.remaining_time

        initiatives_container.append(curr_initiative)

    if args.export_estimates:
        export_initiatives_json(
            args.export_estimates_path, initiatives_container)
