from superpower_workflow.cli import build_parser


def test_parser_run_command():
    parser = build_parser()
    args = parser.parse_args(["run"])
    assert args.command == "run"
    assert args.dry_run is False


def test_parser_run_milestone_flag():
    args = build_parser().parse_args(["run", "--milestone", "p1-m2"])
    assert args.milestone == "p1-m2"


def test_parser_run_dry_run():
    args = build_parser().parse_args(["run", "--dry-run"])
    assert args.dry_run is True


def test_parser_estimate_command():
    args = build_parser().parse_args(["estimate"])
    assert args.command == "estimate"


def test_parser_doctor_command():
    args = build_parser().parse_args(["doctor"])
    assert args.command == "doctor"


def test_parser_status_command():
    args = build_parser().parse_args(["status"])
    assert args.command == "status"
