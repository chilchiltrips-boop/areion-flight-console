"""Open the complete Areion Qt application in a browser on this computer."""
import argparse
import errno
import os
import signal
import sys
import threading
import webbrowser


def main(args=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--no-browser', action='store_true', help='Print the session URL without opening a tab.')
    parser.add_argument('--port', type=int, default=None,
                        help='Loopback port (default 18765, automatically falls back if busy). Use 0 for a random port.')
    options = parser.parse_args(args)
    if options.port is not None and not 0 <= options.port <= 65535:
        parser.error('Choose a port between 0 and 65535.')
    # Keep the complete QWidget application and dialogs on an isolated Qt
    # display; browser events must never be injected into the user's desktop.
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'
    from runtime_setup import prepare_project
    prepare_project(require_gui=True)
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QApplication
    from areion_gui.window import MainWindow
    from browser_host.surface import Surface
    from browser_host.server import Server

    QApplication.setAttribute(Qt.ApplicationAttribute.AA_DontUseNativeDialogs)
    app = QApplication([])
    app.setOrganizationName('Zebjus')
    app.setApplicationName('AreionFlightConsole')
    app.setStyle('Fusion')
    app.setFont(QFont('Sans Serif', 10))
    window = MainWindow()
    surface = Surface(window)
    try:
        http = Server(18765 if options.port is None else options.port, surface.session)
    except OSError as exc:
        if options.port is not None or exc.errno not in (errno.EADDRINUSE, 10048):
            raise
        http = Server(0, surface.session)
    thread = threading.Thread(target=http.serve_forever, name='areion-browser-http', daemon=True)
    thread.start()
    url = http.origin + '/#' + surface.session.token
    print('Areion Flight Console is running on this computer. Use this private session link:', flush=True)
    print(url, flush=True)
    print('Press Ctrl+C in this terminal to close the console.', flush=True)
    if not options.no_browser:
        QTimer.singleShot(0, lambda: webbrowser.open(url))
    signal.signal(signal.SIGINT, lambda *_: window.close())
    if hasattr(signal, 'SIGTERM'):
        signal.signal(signal.SIGTERM, lambda *_: window.close())
    try:
        return app.exec()
    finally:
        http.shutdown()
        http.server_close()


if __name__ == '__main__':
    sys.exit(main())
