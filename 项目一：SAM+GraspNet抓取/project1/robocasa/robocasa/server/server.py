"""
RoboCasa ZMQ simulation server.

Publishes robot state, camera images, and accepts control commands
over ZMQ sockets, enabling algorithm integration from separate conda environments.
"""

import os
import time
import signal
import logging

# --- MuJoCo GL backend selection ---
# Set before importing mujoco/robosuite to avoid GL initialization errors.
if "MUJOCO_GL" not in os.environ:
    if "DISPLAY" in os.environ and os.environ["DISPLAY"]:
        os.environ["MUJOCO_GL"] = "egl"
    else:
        os.environ["MUJOCO_GL"] = "osmesa"

import numpy as np
import zmq
import msgpack

import robocasa  # registers all kitchen environments
import robosuite
from robosuite.controllers import load_composite_controller_config
import robosuite.utils.transform_utils as T
from robosuite.utils.ik_utils import IKSolver, get_nullspace_gains

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("robocasa.server")

CAMERA_NAMES = [
    "robot0_agentview_center",
    "robot0_agentview_left",
    "robot0_agentview_right",
    "robot0_frontview",
    "robot0_eye_in_hand",
]


class RoboCasaServer:
    """ZMQ-based simulation server for robocasa kitchen environments."""

    def __init__(
        self,
        task="Kitchen",
        layout=None,
        style=None,
        seed=42,
        pub_port=5555,
        ctrl_port=5556,
        svc_port=5557,
        host="0.0.0.0",
        cam_width=256,
        cam_height=256,
        control_freq=20,
        no_viewer=False,
    ):
        self.cam_width = cam_width
        self.cam_height = cam_height
        self.control_freq = control_freq
        self.no_viewer = no_viewer
        self.task_name = task
        self._layout = layout
        self._style = style
        self._seed = seed
        self.running = False
        self._refs_initialized = False

        # ---- Build environment ----
        controller_configs = load_composite_controller_config(robot="PandaOmron")

        if no_viewer:
            has_renderer = False
            has_offscreen_renderer = True
        else:
            has_renderer = True
            has_offscreen_renderer = True

        env_kwargs = dict(
            env_name=task,
            robots="PandaOmron",
            controller_configs=controller_configs,
            has_renderer=has_renderer,
            has_offscreen_renderer=has_offscreen_renderer,
            use_camera_obs=False,
            ignore_done=True,
            control_freq=control_freq,
            renderer="mjviewer",
            camera_widths=cam_width,
            camera_heights=cam_height,
        )
        if layout is not None:
            env_kwargs["layout_ids"] = layout
        if style is not None:
            env_kwargs["style_ids"] = style
        if seed is not None:
            env_kwargs["seed"] = seed

        logger.info("Creating environment: task=%s layout=%s style=%s seed=%s", task, layout, style, seed)
        self.env = robosuite.make(**env_kwargs)
        # model not loaded yet (Kitchen uses load_model_on_init=False)

        # ---- ZMQ sockets ----
        self.ctx = zmq.Context()

        self.pub_socket = self.ctx.socket(zmq.PUB)
        self.pub_socket.bind(f"tcp://{host}:{pub_port}")

        self.ctrl_socket = self.ctx.socket(zmq.PULL)
        self.ctrl_socket.bind(f"tcp://{host}:{ctrl_port}")

        self.svc_socket = self.ctx.socket(zmq.REP)
        self.svc_socket.bind(f"tcp://{host}:{svc_port}")

        # ---- Command buffer (hold-last-value per topic) ----
        self._cmd_buffer = {
            "/robot/arm/delta_ee_pose": np.zeros(6, dtype=np.float64),
            "/robot/gripper/command": np.zeros(1, dtype=np.float64),
            "/robot/base/command": np.zeros(3, dtype=np.float64),
            "/robot/torso/command": np.zeros(1, dtype=np.float64),
        }

        # ---- Poller ----
        self.poller = zmq.Poller()
        self.poller.register(self.ctrl_socket, zmq.POLLIN)
        self.poller.register(self.svc_socket, zmq.POLLIN)

        logger.info(
            "Server listening: pub=tcp://%s:%d, ctrl=tcp://%s:%d, svc=tcp://%s:%d",
            host, pub_port, host, ctrl_port, host, svc_port,
        )

    # ====================================================================
    # Initialization (called after first reset when sim is available)
    # ====================================================================

    def _init_env_references(self):
        """Cache robot state indices, camera IDs, IK solver. Call after reset."""
        self.robot = self.env.robots[0]
        self.sim = self.env.sim

        # Arm
        self._arm_jpos_idx = list(self.robot._ref_arm_joint_pos_indexes)
        self._arm_jvel_idx = list(self.robot._ref_arm_joint_vel_indexes)
        self._eef_site_id = self.robot.eef_site_id["right"]

        # Gripper
        self._gripper_jpos_idx = list(self.robot._ref_gripper_joint_pos_indexes["right"])

        # Base
        self._base_jpos_idx = list(self.robot._ref_base_joint_pos_indexes)
        base_joint_names = self.robot.robot_model._base_joints
        self._base_jvel_idx = [
            self.sim.model.get_joint_qvel_addr(n) for n in base_joint_names
        ]

        # Torso
        self._torso_jpos_idx = list(self.robot._ref_torso_joint_pos_indexes)

        # Cameras
        self._cameras = {}
        for cam_name in CAMERA_NAMES:
            try:
                cam_id = self.sim.model.camera_name2id(cam_name)
                self._cameras[cam_name] = cam_id
            except Exception:
                logger.debug("Camera '%s' not in model, skipping", cam_name)
        logger.info("Available cameras: %s", list(self._cameras.keys()))

        # IK solver
        self._ik_solver = self._init_ik_solver()
        if self._ik_solver is None:
            logger.warning("IK solver not available; /robot/arm/solve_ik will return error")

        self._refs_initialized = True

    def _init_ik_solver(self):
        try:
            arm_joint_names = self.robot.robot_model.arm_joints
            grip_site = self.robot.gripper["right"].important_sites["grip_site"]
            robot_config = {
                "end_effector_sites": [grip_site],
                "joint_names": arm_joint_names,
                "mocap_bodies": [],
                "nullspace_gains": get_nullspace_gains(arm_joint_names, {}),
            }
            solver = IKSolver(
                model=self.sim.model._model,
                data=self.sim.data._data,
                robot_config=robot_config,
                damping=5e-2,
                integration_dt=0.1,
                max_dq=4.0,
                input_type="keyboard",
                input_action_repr="absolute",
                input_rotation_repr="quat_wxyz",
                input_ref_frame="world",
            )
            return solver
        except Exception as exc:
            logger.warning("IK solver init failed: %s", exc)
            return None

    # ====================================================================
    # Main loop
    # ====================================================================

    def run(self):
        self.running = True
        step_interval = 1.0 / self.control_freq
        last_step = time.monotonic()

        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, lambda s, f: setattr(self, "running", False))

        self.env.reset()
        if not self._refs_initialized:
            self._init_env_references()

        logger.info("Simulation running (ctrl-C to stop)")

        while self.running:
            events = dict(self.poller.poll(timeout=1))

            if self.ctrl_socket in events:
                self._drain_commands()

            if self.svc_socket in events:
                self._handle_service()

            now = time.monotonic()
            if now - last_step >= step_interval:
                action = self._assemble_action()
                self.env.step(action)

                self._publish_state()
                self._publish_cameras()

                if not self.no_viewer and self.env.viewer is not None:
                    self.env.viewer.update()

                last_step = now

        self._cleanup()

    # ====================================================================
    # Command handling
    # ====================================================================

    def _drain_commands(self):
        while True:
            try:
                parts = self.ctrl_socket.recv_multipart(zmq.NOBLOCK)
                if len(parts) >= 2:
                    topic = parts[0].decode("utf-8")
                    if topic in self._cmd_buffer:
                        val = msgpack.unpackb(parts[1])
                        arr = np.asarray(val, dtype=np.float64)
                        if arr.shape == self._cmd_buffer[topic].shape:
                            self._cmd_buffer[topic] = arr
                        else:
                            logger.warning(
                                "Bad shape for %s: got %s, expected %s",
                                topic, arr.shape, self._cmd_buffer[topic].shape,
                            )
            except zmq.Again:
                break

    def _assemble_action(self):
        action = np.zeros(12, dtype=np.float64)

        # Layout matches HybridMobileBase action_split_indexes:
        #   right[0:6]  right_gripper[6:7]  base[7:10]  torso[10:11]  mode[11]
        action[0:6] = self._cmd_buffer["/robot/arm/delta_ee_pose"]
        action[6] = self._cmd_buffer["/robot/gripper/command"][0]
        base_cmd = self._cmd_buffer["/robot/base/command"]
        action[7:10] = base_cmd
        action[10] = self._cmd_buffer["/robot/torso/command"][0]
        action[11] = 1.0 if np.any(np.abs(base_cmd) > 1e-6) else -1.0

        return action

    # ====================================================================
    # State publishing
    # ====================================================================

    def _publish_state(self):
        sim = self.sim

        # Arm
        eef_mat = sim.data.site_xmat[self._eef_site_id].reshape(3, 3)
        self._pub("/robot/arm/state", {
            "joint_pos": sim.data.qpos[self._arm_jpos_idx].tolist(),
            "joint_vel": sim.data.qvel[self._arm_jvel_idx].tolist(),
            "eef_pos": sim.data.site_xpos[self._eef_site_id].tolist(),
            "eef_quat": T.mat2quat(eef_mat).tolist(),
        })

        # Gripper
        self._pub("/robot/gripper/state", {
            "gripper_qpos": sim.data.qpos[self._gripper_jpos_idx].tolist(),
        })

        # Base
        self._pub("/robot/base/state", {
            "base_pos": sim.data.qpos[self._base_jpos_idx].tolist(),
            "base_vel": sim.data.qvel[self._base_jvel_idx].tolist(),
        })

        # Torso
        self._pub("/robot/torso/state", {
            "torso_height": float(sim.data.qpos[self._torso_jpos_idx][0]),
        })

    # ====================================================================
    # Camera publishing
    # ====================================================================

    def _publish_cameras(self):
        for cam_name, cam_id in self._cameras.items():
            try:
                rgb, depth = self.sim.render(
                    camera_name=cam_name,
                    width=self.cam_width,
                    height=self.cam_height,
                    depth=True,
                )
                # MuJoCo renders bottom-up; flip to top-down
                rgb = np.ascontiguousarray(np.flip(rgb, axis=0))
                depth = np.ascontiguousarray(np.flip(depth, axis=0))

                # MuJoCo mjr_readPixels returns normalized depth [0,1]
                # (0 at near plane, 1 at far plane). Convert to metric meters.
                extent = self.sim.model.stat.extent
                near = self.sim.model.vis.map.znear * extent
                far = self.sim.model.vis.map.zfar * extent
                depth = near / (1.0 - depth * (1.0 - near / far))

                meta_rgb = msgpack.packb({"shape": rgb.shape, "dtype": str(rgb.dtype)})
                self.pub_socket.send_multipart(
                    [f"/cameras/{cam_name}/rgb".encode(), meta_rgb, rgb.tobytes()]
                )

                meta_d = msgpack.packb({"shape": depth.shape, "dtype": str(depth.dtype)})
                self.pub_socket.send_multipart(
                    [f"/cameras/{cam_name}/depth".encode(), meta_d, depth.tobytes()]
                )

            except Exception as exc:
                logger.warning("Camera %s render: %s", cam_name, exc)

        # Publish camera info alongside every frame.
        # The camera pose changes whenever the robot moves (especially
        # with eye-in-hand cameras on a mobile base). A 5-second interval
        # would cause stale extrinsics, breaking pixel→world transforms.
        for cam_name, cam_id in self._cameras.items():
            self._publish_camera_info(cam_name, cam_id)

    def _publish_camera_info(self, cam_name, cam_id):
        model = self.sim.model
        fovy = float(model.cam_fovy[cam_id])
        fx = (self.cam_height / 2.0) / np.tan(np.deg2rad(fovy / 2.0))
        fy = fx
        cx = self.cam_width / 2.0
        cy = self.cam_height / 2.0

        cam_pos = self.sim.data.cam_xpos[cam_id].copy()
        cam_mat = self.sim.data.cam_xmat[cam_id].reshape(3, 3)

        # Depth normalization parameters (for clients to verify metric conversion)
        near = self.sim.model.vis.map.znear * self.sim.model.stat.extent
        far = self.sim.model.vis.map.zfar * self.sim.model.stat.extent

        self._pub(f"/cameras/{cam_name}/info", {
            "intrinsics": [[fx, 0.0, cx], [0.0, fy, cy], [0.0, 0.0, 1.0]],
            "cam_pos": cam_pos.tolist(),
            "cam_quat": T.mat2quat(cam_mat).tolist(),
            "fovy": fovy,
            "width": self.cam_width,
            "height": self.cam_height,
            "depth_near": float(near),
            "depth_far": float(far),
        })

    # ====================================================================
    # Services
    # ====================================================================

    def _handle_service(self):
        try:
            parts = self.svc_socket.recv_multipart()
            topic = parts[0].decode("utf-8")
            params = msgpack.unpackb(parts[1]) if len(parts) > 1 else {}

            if topic == "/env/reset":
                layout_id = params.get("layout_id")
                style_id = params.get("style_id")
                if layout_id is not None and style_id is not None:
                    self.env.layout_and_style_ids = [[layout_id, style_id]]
                self.env.reset()
                for k in self._cmd_buffer:
                    self._cmd_buffer[k] = np.zeros_like(self._cmd_buffer[k])

                # Re-init reference indices (sim may have been rebuilt in hard reset)
                self._init_env_references()
                response = {"status": "ok"}

            elif topic == "/robot/arm/solve_ik":
                response = self._service_solve_ik(params)

            else:
                response = {"status": "error", "message": f"unknown service: {topic}"}

            self.svc_socket.send_multipart([b"ok", msgpack.packb(response)])

        except Exception as exc:
            logger.error("Service error: %s", exc, exc_info=True)
            try:
                self.svc_socket.send_multipart(
                    [b"err", msgpack.packb({"status": "error", "message": str(exc)})]
                )
            except Exception:
                pass

    def _service_solve_ik(self, params):
        if self._ik_solver is None:
            return {"status": "error", "message": "IK solver not available"}
        try:
            target_pos = np.array(params["target_pos"], dtype=np.float64)
            target_quat = np.array(params["target_quat"], dtype=np.float64)
            target_action = np.concatenate([target_pos, target_quat])
            joint_angles = self._ik_solver.solve(target_action)
            return {"status": "ok", "joint_angles": joint_angles.tolist()}
        except Exception as exc:
            return {"status": "unreachable", "message": str(exc)}

    # ====================================================================
    # Helpers
    # ====================================================================

    def _pub(self, topic, data):
        self.pub_socket.send_multipart([topic.encode(), msgpack.packb(data)])

    def _cleanup(self):
        logger.info("Shutting down ...")
        if self.env.viewer is not None:
            try:
                self.env.viewer.close()
            except Exception:
                pass
        try:
            self.env.sim._render_context.close()
        except Exception:
            pass
        self.ctx.destroy(linger=500)
        logger.info("Server stopped.")
