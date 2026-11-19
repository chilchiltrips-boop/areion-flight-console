"""Start the Areion Flight Console or check its installation."""
import argparse
from runtime_setup import prepare_project, ProjectSetupError, import_failure, setup_report

def main():
    parser=argparse.ArgumentParser(description='Areion Flight Console 3.12.3')
    parser.add_argument('--check',action='store_true',help='Verify imports and show interpreter/SDK paths without connecting')
    options=parser.parse_args()
    try:
        prepare_project(require_gui=True)
        from areion_gui.window import launch
        if options.check:
            print(setup_report())
            return 0
    except ProjectSetupError as error:
        raise SystemExit(str(error)) from None
    except ImportError as error:
        raise SystemExit(import_failure(error)) from None
    return launch()

if __name__=='__main__':
    raise SystemExit(main())
