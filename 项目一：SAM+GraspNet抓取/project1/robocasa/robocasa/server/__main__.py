"""
CLI entry point for the RoboCasa ZMQ simulation server.

    python -m robocasa.server --task DefrostByCategory --layout 11 --style 14
"""

import argparse

from robocasa.server import RoboCasaServer


def main():
    p = argparse.ArgumentParser(
        description="RoboCasa ZMQ simulation server"
    )

    # Scene
    p.add_argument("--task", default="DefrostByCategory",
                   help="Task / environment name (default: DefrostByCategory)")
    p.add_argument("--layout", type=int, default=11,
                   help="Kitchen layout ID (default: 11)")
    p.add_argument("--style", type=int, default=14,
                   help="Kitchen style ID (default: 14)")

    # Network
    p.add_argument("--host", default="0.0.0.0",
                   help="Bind address (default: 0.0.0.0)")
    p.add_argument("--pub-port", type=int, default=5555,
                   help="Observation publish port (default: 5555)")
    p.add_argument("--ctrl-port", type=int, default=5556,
                   help="Control receive port (default: 5556)")
    p.add_argument("--srv-port", type=int, default=5557,
                   help="Service port (default: 5557)")

    # Camera
    p.add_argument("--cam-width", type=int, default=256,
                   help="Camera image width (default: 256)")
    p.add_argument("--cam-height", type=int, default=256,
                   help="Camera image height (default: 256)")

    # Simulation
    p.add_argument("--control-freq", type=int, default=20,
                   help="Control frequency in Hz (default: 20)")
    p.add_argument("--no-viewer", action="store_true",
                   help="Run headless (no mjviewer window)")
    p.add_argument("--seed", type=int, default=None,
                   help="Random seed for deterministic object placement (default: random)")

    args = p.parse_args()

    server = RoboCasaServer(
        task=args.task,
        layout=args.layout,
        style=args.style,
        seed=args.seed,
        pub_port=args.pub_port,
        ctrl_port=args.ctrl_port,
        svc_port=args.srv_port,
        host=args.host,
        cam_width=args.cam_width,
        cam_height=args.cam_height,
        control_freq=args.control_freq,
        no_viewer=args.no_viewer,
    )
    server.run()


if __name__ == "__main__":
    main()
