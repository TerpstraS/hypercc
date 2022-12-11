import warnings
import sys
import locale
# import noodles
import argparse

from .workflow import generate_report, run, run_single
from .units import MONTHS


warnings.simplefilter(action='ignore', category=FutureWarning)
locale.setlocale(locale.LC_ALL, '')


def print_nlesc_logo():
    print("\n     \033[47;30m Netherlands\033[48;2;0;174;239;37m▌"
          "\033[38;2;255;255;255me\u20d2Science\u20d2\033[37m▐"
          "\033[47;30mcenter \033[m"
          "          \033[0;90m╒═══════════════════════════╕\033[m\n"
          "                  and                       "
          "\033[0;90m│ \033[1;37mHyperCanny Climate module\033[0;90m │\n"
          " \033[47;30m \033[38;2;42;128;41;4m⊓ \033[24m"
          "\033[38;2;0;74;109m Wageningen"
          "\033[38;2;42;128;41m University & Research \033[m  "
          "    \033[90m╰───────────────────────────╯\033[m\n", file=sys.stderr)


def make_argument_parser():
    """Create the argument parser for the `hypercc` script."""

    parser = argparse.ArgumentParser(
        prog='hypercc',
        description="Detect edges in climate data")
    parser.add_argument(
        "--data-folder", help="path to search for NetCDF files "
        "(default: %(default)s)",
        default='.', dest='data_folder')
    parser.add_argument(
        "--pi-control-folder", help="path to search for piControl data (if"
        " different than data folder", dest='pi_control_folder')
    parser.add_argument(
        "--output-folder", help="folder where to put output of script "
        "(default: %(default)s)",
        default='.', dest='output_folder')

    parser.add_argument(
        "--single", help="force running in single threaded mode",
        dest="single", action="store_true")

    subparser = parser.add_subparsers(
        help="command to run", dest='command')

    report_parser = subparser.add_parser(
        "report", help="generate complete report")
    report_parser.set_defaults(func=generate_report)

    report_parser.add_argument(
        "--model", help="model name in CMIP5 naming scheme",
        required=True, dest='model')
    report_parser.add_argument(
        "--scenario", help="scenario name in CMIP5 naming scheme",
        required=True, dest='scenario')
    report_parser.add_argument(
        "--variable", help="variable name in CMIP5 naming scheme",
        required=True, dest='variable')
    report_parser.add_argument(
        "--realization", help="realization name in CMIP5 naming scheme "
        "(default: %(default)s)",
        default='r1i1p1', dest='realization')
    report_parser.add_argument(
        "--frequency", help="frequency name (table_id)",
        required=True, dest="frequency"
    )
    report_parser.add_argument(
        "--extension", help="extension to data files (default: %(default)s)",
        default='gr.nc', dest='extension')
    report_parser.add_argument(
        "--annual", help="compute annual mean of data instead of selecting "
        " a single month (--month argument is ignored)", dest='annual',
        action='store_true')
    report_parser.add_argument(
        "--month", help="which month to study, give abbreviated month name "
        "as by your locale, or a number in the inclusive range of [1-12].",
        default=MONTHS[0],
        choices=MONTHS + list(map(str, range(1, 13)))
        + list(map('{:02}'.format, range(1, 10))))
    report_parser.add_argument(
        "--sigma-x", help="spacial smoothing scale, quantity with unit "
        "(default: 200 km)",
        nargs=2, default=['200', 'km'], dest='sigma_x')
    report_parser.add_argument(
        "--sigma-t", help="temporal smoothing scale, quantity with unit"
        "(default: 10 year)",
        nargs=2, default=['10', 'year'], dest='sigma_t')
    report_parser.add_argument(
        "--calibration-quartile", help="quartile of sobel response function"
        " to equalize in calibration.",
        choices=['min', '1st', 'median', '3rd', 'max'],
        default='3rd', dest='calibration_quartile'),
    report_parser.add_argument(
        "--upper-threshold-ref", help="reference for upper threshold "
        "(default: %(default)s)", choices=['pi-control-max'],
        default='pi-control-max', dest='upper_threshold_ref')
    report_parser.add_argument(
        "--lower-threshold-ref", help="reference for lower threshold "
        "(default: %(default)s)", choices=[
            'pi-control-3', 'pi-control-max'],
        default='pi-control-3', dest='lower_threshold_ref')
    report_parser.add_argument(
        "--upper-threshold-frac", help="sets value of upper threshold relative to reference"
        "(default: 1)",
        nargs=1, default=['1'], dest='upper_threshold_frac')
    report_parser.add_argument(
        "--lower-threshold-frac", help="sets value of lower threshold relative to reference"
        "(default: 1)",
        nargs=1, default=['1'], dest='lower_threshold_frac')
    report_parser.add_argument(
        "--sobel-scale", help="scaling of time/space in magnitude of Sobel"
        " operator, should have dimensionality of velocity. (default: "
        "10 km/year)", nargs=2, default=['10', 'km/year'], dest='sobel_scale')
    report_parser.add_argument(
        "--no-taper", help="taper data to handle land/sea mask.",
        dest='taper', action='store_false')

    return parser


if __name__ == "__main__":
    import logging

    # disable interactive plotting
    import matplotlib
    matplotlib.use('SVG')

    print_nlesc_logo()
    logging.getLogger('root').setLevel(logging.WARNING)
    # logging.getLogger('noodles').setLevel(logging.WARNING)
    logging.info("This message should show.")

    parser = make_argument_parser()
    args = parser.parse_args()
    if args.month not in MONTHS:
        args.month = MONTHS[int(args.month) - 1]

    if args.command == 'report':
        workflow = args.func(args)
        if args.single:
            results = run_single(workflow)
        else:
            results = run(workflow)

        if results:
            print(results['calibration'])
            print()

            # for name, result in results.items():
            #     if noodles.failed(result):
            #         print("==========================================")
            #         print("Result {} failed: {}".format(name, result))
            #         print("==========================================")
            #         print()
            print("max maxTgrad:", results['statistics']['max_maxTgrad'])
            print("max abruptness:", results['statistics']['max_abruptness'])

        else:
            print(results)
