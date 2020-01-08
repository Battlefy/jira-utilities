import argparse
import epicTimeRollup
from dataclasses import dataclass, asdict
import os
import sys
import datetime
import shutil
import json
from jira import JIRA
from subprocess import Popen


@dataclass
class MonthWorkload:
    month: int
    epics: []
    summed_time: float
    remaining_time: float


@dataclass
class Initiative:
    initiative: JIRA.issue
    epics: []
    summed_time: float
    remaining_time: float
    incomplete_estimated_count: int
    incomplete_unestimated_count: int

    def calculate_estimate_counts(self):
        self.incomplete_unestimated_count = 0
        self.incomplete_estimated_count = 0

        for epic in self.epics:
            self.incomplete_estimated_count += epic.incomplete_estimated_count
            self.incomplete_unestimated_count += epic.incomplete_unestimated_count

    def dict(self):
        epic_json = []
        for epic in self.epics:
            epic_json.append(epic.dict())

        self.calculate_estimate_counts()

        return {'key': self.initiative.key, 'summary': self.initiative.fields.summary, 'summed_time': self.summed_time, 'remaining_time': self.remaining_time, 'incomplete_estimated_count': self.incomplete_estimated_count, 'incomplete_unestimated_count': self.incomplete_unestimated_count, 'epics': epic_json}


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
    parser.add_argument("--story_point_weight", default=5)
    parser.add_argument("--story_point_weight_ceiling", default=25)
    parser.add_argument("--import_project_configs_path")
    parser.add_argument("--filter_month", action='store_true')
    parser.add_argument("--filter_month_numbers")
    parser.add_argument("--update_initiative_estimates", action='store_true')
    parser.add_argument("--create_calendar_schedule", action='store_true')

    args = parser.parse_args(args=args_list)

    if args.filter_month == True:
        if args.filter_month_numbers is None:
            argparse.ArgumentError(
                "User provided --filter_month option but did not provide --filter_month_numbers")
            sys.exit(-2)
        else:
            args.filter_month_numbers = args.filter_month_numbers.split(",")

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
    INITIAL_TIME_KEY = "customfield_11609"
    REMAINING_TIME_KEY = "customfield_11639"
    CONFIDENCE_INTERVAL_KEY = "customfield_11641"
    INCOMPLETE_ISSUE_COUNT_KEY = "customfield_11642"
    START_DATE_KEY = "customfield_11600"

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
        filtered_keys = []

        if args.filter_month == True:
            for epic_key in keys:
                epic_pre_add = jira.issue(epic_key)
                if epic_pre_add.fields.duedate is not None:
                    date_object = datetime.datetime.strptime(
                        epic_pre_add.fields.duedate, "%Y-%m-%d")
                    if str(date_object.month) in args.filter_month_numbers:
                        filtered_keys.append(epic_key)
                else:
                    # if no due date, just include
                    filtered_keys.append(epic_key)
        else:
            filtered_keys.extend(keys)

        new_args = create_epic_rollup_args(
            args_list, initiative, filtered_keys)
        epics_container = epicTimeRollup.execute(
            new_args) if len(filtered_keys) != 0 else []

        curr_initiative = Initiative(
            initiative_issue, epics_container, 0.0, 0.0, 0, 0)

        for epic in epics_container:
            curr_initiative.summed_time += epic.summed_time
            curr_initiative.remaining_time += epic.remaining_time

        initiatives_container.append(curr_initiative)

    if args.update_initiative_estimates:
        # update the SP estimate on the initiatives
        for initiative in initiatives_container:
            initiative.calculate_estimate_counts()

            ratio = 0 if initiative.incomplete_estimated_count == 0 and initiative.incomplete_unestimated_count == 0 else (
                initiative.incomplete_estimated_count / (initiative.incomplete_estimated_count + initiative.incomplete_unestimated_count))
            ratio = ratio * 100

            story_point_average = 0 if initiative.incomplete_estimated_count == 0 else initiative.remaining_time / \
                initiative.incomplete_estimated_count

            if ratio != 0:
                # weight in the distribution of story points
                # if the average story points per ticket is <=story_point_weight (default 5)
                # retain our weighting; if not, reduce confidence rating
                # by at most story_point_weight_ceiling (default 80%)
                if story_point_average < args.story_point_weight:
                    story_point_average = args.story_point_weight
                elif story_point_average > args.story_point_weight_ceiling:
                    story_point_average = args.story_point_weight_ceiling

                ratio *= (args.story_point_weight/story_point_average)

            if ratio > 95:
                ratio = 95

            initiative.initiative.update(fields={
                INITIAL_TIME_KEY: initiative.summed_time})
            initiative.initiative.update(fields={
                REMAINING_TIME_KEY: initiative.remaining_time})
            initiative.initiative.update(fields={
                CONFIDENCE_INTERVAL_KEY: int(ratio)})
            initiative.initiative.update(fields={
                                         INCOMPLETE_ISSUE_COUNT_KEY: initiative.incomplete_estimated_count+initiative.incomplete_unestimated_count})

    if args.export_estimates:
        export_initiatives_json(
            args.export_estimates_path, initiatives_container)

    if args.create_calendar_schedule:
        month_distributions = {}
        skipped_epics = []
        print("Calculating calendar rooted capacity demand...")
        for initiative in initiatives_container:
            for epic in initiative.epics:
                start_date_object = None
                end_date_object = None

                if epic.epic.fields.duedate is not None:
                    end_date_object = datetime.datetime.strptime(
                        epic.epic.fields.duedate, "%Y-%m-%d")
                elif initiative.initiative.fields.duedate is not None:
                    end_date_object = datetime.datetime.strptime(
                        initiative.initiative.fields.duedate, "%Y-%m-%d")
                else:
                    skipped_epics.append(epic)
                    continue

                if getattr(epic.epic.fields, START_DATE_KEY) is not None:
                    start_date_object = datetime.datetime.strptime(
                        getattr(epic.epic.fields, START_DATE_KEY), "%Y-%m-%d")
                else:
                    start_date_object = datetime.datetime(
                        end_date_object.year, end_date_object.month, end_date_object.day)

                delta_days = (end_date_object - start_date_object).day

                iterations = end_date_object.month + 1 - start_date_object.month

                for i in range(iterations):
                    month_number = start_date_object.month + i
                    if month_number not in month_distributions:
                        month_distributions[month_number] = MonthWorkload(
                            month_number, [], 0.0, 0.0)
                        month_distributions[month_number].epics.append(epic)

                    month_distributions[month_number].summed_time += float(
                        epic.summed_time / iterations)
                    month_distributions[month_number].remaining_time += float(
                        epic.remaining_time / iterations)

        print("Done")
