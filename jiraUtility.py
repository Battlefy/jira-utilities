import argparse
import initiativeTimeRollup
import epicTimeRollup


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--command", help="The command to issue [epicTimeRollup, initiativeTimeRollup]. All trailing commands will be passed through to the underlaying command.", required=True)

    args, passthrough = parser.parse_known_args()
    return args, passthrough


def main():
    args, passthrough = parse_args()
    if args.command == "initiativeTimeRollup":
        print("Executing {}".format(args.command))
        initiativeTimeRollup.execute(passthrough)
    elif args.command == "epicTimeRollup":
        print("Executing {}".format(args.command))
        epicTimeRollup.execute(passthrough)
    else:
        print("Unknown command {}".format(args.command))


main()
