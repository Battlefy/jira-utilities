import argparse
import epicTimeRollup
from dataclasses import dataclass, asdict
import os
import shutil
from jira import JIRA
from subprocess import Popen


@dataclass
class Initiative:
    initiative: JIRA.issue
    epics: []
    summed_time: float


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
    initiatives_struct = []

    for initiative in initiatives:
        print("Obtaining roll-up for {}".format(initiative))
        initiative_issue = jira.issue(initiative)
        keys = [
            x.inwardIssue.key for x in initiative_issue.fields.issuelinks if 'BI' not in x.inwardIssue.key]
        new_args = create_epic_rollup_args(args_list, initiative, keys)
        epics_container = epicTimeRollup.execute(new_args)

        curr_initiative = Initiative(initiative_issue, epics_container, 0.0)

        for epic in epics_container:
            curr_initiative.summed_time += epic.summed_time

        initiatives_struct.append(curr_initiative)

    for initiative in initiatives_struct:
        print(initiative)
