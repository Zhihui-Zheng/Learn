"""
Standalone ZMQ client for the RoboCasa simulation server.

Zero dependencies on robosuite / robocasa / MuJoCo.
Requires only: pyzmq, msgpack, numpy.

Usage:
    from robocasa.server.client import RoboCasaClient

    client = RoboCasaClient(host="localhost")
    client.connect()

    # Read latest state
    state = client.recv_state()
    print(state["/robot/arm/state"])

    # Send control commands
    client.send_delta_ee_pose([0.01, 0.0, -0.01, 0.0, 0.0, 0.0])
    client.send_gripper(1.0)   # close
    client.send_base([0.1, 0.0, 0.0])

    # Call services
    result = client.reset(layout_id=11, style_id=14)
    ik = client.solve_ik(target_pos=[0.5, 0.0, 0.8],
                         target_quat=[1.0, 0.0, 0.0, 0.0])
"""

import time
import threading
import logging

import numpy as np
import zmq
import msgpack

logger = logging.getLogger("robocasa.client")


class RoboCasaClient:
    def __init__(
        self,
        host="127.0.0.1",
        pub_port=5555,
        ctrl_port=5556,
        svc_port=5557,
    ):
        self.host = host
        self.ports = {"pub": pub_port, "ctrl": ctrl_port, "svc": svc_port}

        self.ctx = zmq.Context()

        # SUB socket: receive observations
        self.sub = self.ctx.socket(zmq.SUB)
        self.sub.setsockopt(zmq.SUBSCRIBE, b"/robot/")
        self.sub.setsockopt(zmq.SUBSCRIBE, b"/cameras/")
        self.sub.setsockopt(zmq.SUBSCRIBE, b"/sim/")
        self.sub.setsockopt(zmq.RCVTIMEO, 1000)

        # PUSH socket: send control commands
        self.push = self.ctx.socket(zmq.PUSH)

        # REQ socket: service calls
        self.req = self.ctx.socket(zmq.REQ)
        self.req.setsockopt(zmq.RCVTIMEO, 30000)
        self.req.setsockopt(zmq.LINGER, 500)
        self.req.setsockopt(zmq.REQ_RELAXED, 1)

        # Data stores
        self._latest = {}          # topic -> decoded payload
        self._camera_rgb = {}      # cam_name -> np.ndarray (H, W, 3) uint8
        self._camera_depth = {}    # cam_name -> np.ndarray (H, W) float32
        self._camera_info = {}     # cam_name -> info dict

        self._connected = False
        self._recv_thread = None

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def connect(self):
        self.push.connect(f"tcp://{self.host}:{self.ports['ctrl']}")
        self.req.connect(f"tcp://{self.host}:{self.ports['svc']}")
        self.sub.connect(f"tcp://{self.host}:{self.ports['pub']}")
        # brief pause for async ZMQ connections to establish
        time.sleep(0.1)
        self._connected = True
        logger.info("Connected to %s (pub:%d ctrl:%d svc:%d)",
                     self.host, *self.ports.values())

    def close(self):
        self._connected = False
        self.ctx.destroy(linger=500)

    # ------------------------------------------------------------------
    # Receive state
    # ------------------------------------------------------------------

    def recv_state(self, timeout=0):
        """Poll for new data. Returns self for chaining."""
        while True:
            try:
                parts = self.sub.recv_multipart(flags=zmq.NOBLOCK if timeout == 0 else 0)
                self._dispatch(parts)
                timeout = 0  # switched to non-blocking after first msg
            except zmq.Again:
                break
        return self

    def recv_state_blocking(self, timeout=1.0):
        """Block until at least one message received."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                parts = self.sub.recv_multipart(flags=zmq.NOBLOCK)
                self._dispatch(parts)
                return True
            except zmq.Again:
                time.sleep(0.001)
        return False

    def _dispatch(self, parts):
        if len(parts) < 2:
            return
        topic = parts[0].decode("utf-8")

        if topic.endswith("/rgb") or topic.endswith("/depth"):
            # Image message: [topic, meta_msgpack, raw_bytes]
            if len(parts) >= 3:
                meta = msgpack.unpackb(parts[1])
                raw = parts[2]
                img = np.frombuffer(raw, dtype=np.dtype(meta["dtype"]))
                img = img.reshape(meta["shape"])
                if topic.endswith("/rgb"):
                    self._camera_rgb[topic] = img
                else:
                    self._camera_depth[topic] = img
        else:
            # Regular message: [topic, payload_msgpack]
            self._latest[topic] = msgpack.unpackb(parts[1])

    # ------------------------------------------------------------------
    # Control commands
    # ------------------------------------------------------------------

    def _send_cmd(self, topic, value):
        arr = np.asarray(value, dtype=np.float64).ravel()
        self.push.send_multipart([topic.encode(), msgpack.packb(arr.tolist())])

    def send_delta_ee_pose(self, delta):
        """Send arm delta EE pose: [dx, dy, dz, droll, dpitch, dyaw] (6 floats)."""
        self._send_cmd("/robot/arm/delta_ee_pose", delta)

    def send_gripper(self, action):
        """Send gripper command: float (-1=open, 1=close)."""
        self._send_cmd("/robot/gripper/command", [float(action)])

    def send_base(self, vel):
        """Send base velocity: [vx, vy, omega] (3 floats)."""
        self._send_cmd("/robot/base/command", vel)

    def send_torso(self, height):
        """Send torso target height: float."""
        self._send_cmd("/robot/torso/command", [float(height)])

    # ------------------------------------------------------------------
    # Services
    # ------------------------------------------------------------------

    def _call_svc(self, topic, params=None):
        if params is None:
            params = {}
        self.req.send_multipart([topic.encode(), msgpack.packb(params)])
        status, payload = self.req.recv_multipart()
        return msgpack.unpackb(payload)

    def reset(self, layout_id=None, style_id=None):
        params = {}
        if layout_id is not None:
            params["layout_id"] = layout_id
        if style_id is not None:
            params["style_id"] = style_id
        return self._call_svc("/env/reset", params)

    def solve_ik(self, target_pos, target_quat):
        return self._call_svc(
            "/robot/arm/solve_ik",
            {
                "target_pos": list(target_pos),
                "target_quat": list(target_quat),
            },
        )

    # ------------------------------------------------------------------
    # Convenience accessors
    # ------------------------------------------------------------------

    @property
    def arm_state(self):
        return self._latest.get("/robot/arm/state", {})

    @property
    def gripper_state(self):
        return self._latest.get("/robot/gripper/state", {})

    @property
    def base_state(self):
        return self._latest.get("/robot/base/state", {})

    @property
    def torso_state(self):
        return self._latest.get("/robot/torso/state", {})

    def camera_rgb(self, name="agentview_center"):
        return self._camera_rgb.get(f"/cameras/robot0_{name}/rgb")

    def camera_depth(self, name="agentview_center"):
        return self._camera_depth.get(f"/cameras/robot0_{name}/depth")

    def camera_info(self, name="agentview_center"):
        return self._latest.get(f"/cameras/robot0_{name}/info", {})
