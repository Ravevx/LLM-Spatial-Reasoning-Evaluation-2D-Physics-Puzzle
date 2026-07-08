#check and update the resources/initial prompts and refined prompts as you want for the agent to work.
#currently available in english,spanish,german ( initial /refined) for each ( first attempt and failed attempt)

from __future__ import annotations
import io
import json
import logging
import random
import re
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Tuple
import uuid
from clemcore import backends
import clemcore.clemgame.metrics as _met
if not hasattr(_met, "METRIC_REQUEST_SUCCESS"):
    _met.METRIC_REQUEST_SUCCESS = _met.METRIC_REQUEST_SUCCESS_RATIO
import matplotlib.pyplot as plt
import matplotlib.patches as patches
import pymunk
from matplotlib.backends.backend_agg import FigureCanvasAgg as FigureCanvas
from PIL import Image
import math
from clemcore.backends import Model
from clemcore.clemgame import GameBenchmark, GameMaster, GameScorer, Player, DialogueGameMaster, metrics as m
log = logging.getLogger(__name__)

_TMP_IMG_DIR = Path(tempfile.gettempdir()) / "phys_puzzle_keyframes"
_TMP_IMG_DIR.mkdir(exist_ok=True)

def _dump_images(imgs: List[Image.Image]) -> List[str]:
    paths = []
    for im in imgs:
        f = (_TMP_IMG_DIR / f"{uuid.uuid4().hex}.png").as_posix()
        im.save(f, format="PNG")
        paths.append(f)
    return paths

class PhysicsPuzzleSetup:

    def __init__(self, cfg: Dict[str, Any], game_id: str, game_instance: Dict[str, Any]):
        self.cfg = cfg
        self.w, self.h = cfg["width"], cfg["height"]
        self.fps = cfg.get("fps", 60)
        self.max_steps = cfg.get("sim_steps", 300)

        self.space = pymunk.Space()
        self.space.gravity = (0, 900)

        self.collision_count = 0
        self.collision_points: List[Dict[str, Any]] = []
        self.keyframes: List[Image.Image] = []
        self._create_border()
        self.game_instance = game_instance
        self.obstacles = game_instance.get("obstacles")
        self.ball_dyn = self._create_ball((0, -100), "blue", 1, False)
        self.ball_tgt = self._create_ball((300, 500), "green", 2, True)
        self._add_obstacles()
        self._register_collision_logger()

    def _create_border(self):
        static_body = self.space.static_body
        border_points = [
            ((50, 50), (self.w - 50, 50)),
            ((50, self.h - 50), (self.w - 50, self.h - 50)),
            ((50, 50), (50, self.h - 50)),
            ((self.w - 50, 50), (self.w - 50, self.h - 50))
        ]
        for a, b in border_points:
            seg = pymunk.Segment(static_body, a, b, 5)
            seg.elasticity = 0.8
            seg.collision_type = 0 
            self.space.add(seg)
            
    def _add_obstacles(self):
        static_body = self.space.static_body
        for ob in self.obstacles:
            a, b = ob["start_point"], ob["end_point"]
            seg = pymunk.Segment(static_body, a, b, ob.get("thickness", 5))
            seg.elasticity = 0.8
            seg.friction = 0.5
            seg.collision_type = 3
            self.space.add(seg)

    def _create_ball(self, pos: Tuple[float, float], color: str, ctype: int, static: bool):
        if static:
            body = pymunk.Body(body_type=pymunk.Body.STATIC)
        else:
            mass = 1
            radius = 15
            moment = pymunk.moment_for_circle(mass, 0, radius)
            body = pymunk.Body(mass, moment)
        body.position = pos
        shape = pymunk.Circle(body, 18)
        shape.color = color
        shape.collision_type = ctype
        shape.elasticity = 0.7
        shape.friction = 0.2
        self.space.add(body, shape)
        return body, shape

    def _register_collision_logger(self):
        def on_col(arbiter, space, data):
            self.collision_count += 1
            for point in arbiter.contact_point_set.points:
                self.collision_points.append({
                    "x": point.point_a.x,
                    "y": point.point_a.y,
                    "desc": f"Collision #{self.collision_count}"
                })
            self._save_frame()
            return True

        # collisions: dynamic ball (1) vs border(0) vs target(2) vs obstacles(3)
        self.space.add_collision_handler(1, 0).begin = on_col
        self.space.add_collision_handler(1, 2).begin = on_col
        self.space.add_collision_handler(1, 3).begin = on_col

    def simulate(self, drop_x: float):
        dyn_body, _ = self.ball_dyn
        dyn_body.position = (drop_x, 100)
        dyn_body.velocity = (0, 0)
        self.collision_count = 0
        self.collision_points.clear()
        self.keyframes.clear()
        self._save_frame()

        target_pos = self.ball_tgt[0].position
        goal_reached = False
        steps_to_goal = None
        still_frames = 0  # counter for consecutive frames where ball is almost still
        velocity_threshold = 5.0  # px/s, adjust if needed
        max_still_frames = 30     # wait half a second at 60fps

        step = 0
        while True:
            step += 1
            self.space.step(1 / self.fps)

            # check if reached target
            if dyn_body.position.get_distance(target_pos) <= 36:
                goal_reached = True
                steps_to_goal = step
                self._save_frame()
                break

            # check if ball has nearly stopped moving
            if dyn_body.velocity.length < velocity_threshold:
                still_frames += 1
            else:
                still_frames = 0

            if still_frames >= max_still_frames:
                break

        self._save_frame()
        final_dist = dyn_body.position.get_distance(target_pos)
        if len(self.keyframes) > 10:
            total_frames = len(self.keyframes)
            indices = [int(i * total_frames / 10) for i in range(10)]
            self.keyframes = [self.keyframes[i] for i in indices]
        return (
            goal_reached,
            self.keyframes.copy(),
            self.collision_count,
            steps_to_goal,
            final_dist,
            self.collision_points.copy(),
        )

    def _save_frame(self) -> None:
        fig, ax = plt.subplots(figsize=(3, 3))
        ax.set_xlim(0, self.w)
        ax.set_ylim(0, self.h)
        ax.set_aspect("equal")
        ax.axis("on")
        for ob in self.obstacles:
            a, b = ob["start_point"], ob["end_point"]
            ax.plot([a[0], b[0]], [a[1], b[1]],
                    color="black", lw=ob.get("thickness", 5))
        for s in self.space.shapes:
            if isinstance(s, pymunk.Segment):
                ax.plot([s.a.x, s.b.x], [s.a.y, s.b.y], 'gray', lw=4)
            elif isinstance(s, pymunk.Circle):
                ax.add_patch(patches.Circle((s.body.position.x,
                                             s.body.position.y),
                                            s.radius, color=s.color))
        ax.invert_yaxis()
        canvas = FigureCanvas(fig)
        canvas.draw()
        img = Image.frombuffer("RGBA", canvas.get_width_height(),
                               canvas.buffer_rgba(), "raw", "RGBA", 0, 1
                               ).convert("RGB")
        plt.close(fig)
        self.keyframes.append(img)

    def draw_initial_environment(self) -> Image.Image:
        fig, ax = plt.subplots(figsize=(3, 3), dpi=100)
        ax.set_xlim(0, self.w)
        ax.set_ylim(0, self.h)
        ax.set_aspect("equal")
        ax.axis("on")
        border_pts = [
            ((50, 50), (self.w - 50, 50)),
            ((50, self.h - 50), (self.w - 50, self.h - 50)),
            ((50, 50), (50, self.h - 50)),
            ((self.w - 50, 50), (self.w - 50, self.h - 50)),
        ]
        for a, b in border_pts:
            ax.plot([a[0], b[0]], [a[1], b[1]], color="gray", lw=4)
        for ob in self.obstacles:
            a, b = ob["start_point"], ob["end_point"]
            ax.plot([a[0], b[0]], [a[1], b[1]],
                    color="black", lw=ob.get("thickness", 5))
        ax.add_patch(patches.Circle((300, 500), 15, color="green"))
        ax.invert_yaxis()
        canvas = FigureCanvas(fig)
        canvas.draw()
        img = Image.frombuffer("RGBA", canvas.get_width_height(),
                               canvas.buffer_rgba(), "raw", "RGBA", 0, 1
                               ).convert("RGB")
        plt.close(fig)
        return img

class BallDropper(Player):
    def __init__(self, model: Model):
        super().__init__(model)
        self._model = model

    def _custom_response(self, context: Dict) -> str:
        drop_x = random.randint(100, 500)
        return f"DROP {drop_x}"

class PhysicsPuzzleMaster(DialogueGameMaster):
    PLAYER_ID = "Player 1"
    def __init__(self, name: str, path: Path, experiment: Dict[str, Any], models: List[Any]):
        super().__init__(name, path, experiment, models)
        cfg = experiment.get("config", {})
        self.max_turns = cfg.get("max_turns", 3)
        self.init_prompt = cfg.get("initial_prompt", "")
        self.ref_prompt_t = cfg.get("refined_prompt", "")
        self.regex = cfg.get("regex", "")
        self.PARSE = re.compile(self.regex, re.I)
        self.mode_of_game = cfg.get("mode","")
        self.env = None
        self.turns = 0
        self.goal = False
        self.collisions = 0
        self.steps_to_goal = None
        self.final_dist = None
        self.drop_x = None
        self.current_prompt = self.init_prompt
        self.frames = []
        self._turn_log: List[List[Dict[str, str]]] = []
    
    def log_turn(self, *events: Dict[str, str]) -> None:
        self._turn_log.append(list(events))
        if getattr(self, "game_recorder", None):
            try:
                self.game_recorder.record_turn(list(events))
            except AttributeError:
                pass

    def _on_setup(self, game_instance):
        game_id = game_instance.get("game_id", "")
        self.env = PhysicsPuzzleSetup(
            self.experiment.get("config", {}),
            game_id,
            game_instance,
        )
        self.initial_img = self.env.draw_initial_environment()
        self.player = BallDropper(self.player_models[0])
        self.add_player(self.player)
        if getattr(self, "game_recorder", None):
            self.game_recorder.log_player(
                self.PLAYER_ID,
                "Dropper",
                getattr(self.player_models[0], "name", "LLM"),
            )
        self.dropper = self.player

    def _does_game_proceed(self) -> bool:
        if self.turns >= self.max_turns:
            return False
        if self.goal:
            return False
        return True
    
    def setup(self, **game_instance):
        self._on_setup(game_instance)

    def play(self) -> None:
        if self.mode_of_game == "multimodal" : #MultiModal Loop (Text + Images)
            prompt = self.init_prompt
            frames = [self.initial_img]
            for turn_idx in range(self.max_turns):
                self.turns = turn_idx + 1
                user_msg = {
                    "role": "user",
                    "content": prompt,
                    "image": _dump_images(frames),
                }
                reply = self.player(user_msg)
                print(f"Turn {turn_idx+1} · LLM reply → {reply}")
                self.log_turn(
                    {"from": "GM", "content": prompt},
                    {"from": "Player 1", "content": reply},
                )
                m = self.PARSE.search(reply)
                drop_x = int(m.group(1))
                (self.goal,
                frames,
                self.collisions,
                self.steps_to_goal,
                self.final_dist,
                self.collision_points) = self.env.simulate(drop_x)
                _dump_images(frames)
                if getattr(self, "game_recorder", None):
                    summary = (
                        f"drop_x={drop_x}, "
                        f"collisions={self.collisions}, "
                        f"goal={self.goal}, "
                        f"steps={self.steps_to_goal}, "
                        f"dist={self.final_dist:.1f}"
                    )
                    self.game_recorder.log_event("GM", "GM", {"type": "sim_result", "content": summary})
                if self.goal:
                    break
                prompt = self.ref_prompt_t.format(drop_x=drop_x) # Updating the prompt with the prev drop location.
            self.turns = turn_idx + 1
            self._on_after_game()
        
        else: # Textual Model Loop where self.mode_of_game is = "textual"
            prompt = self.init_prompt.format(obstacles_str=self.env.obstacles)
            for turn_idx in range(self.max_turns):
                self.turns = turn_idx + 1
                user_msg = {
                    "role": "user",
                    "content": prompt,
                }
                reply = self.dropper(user_msg)
                print(f"Turn {turn_idx + 1} · LLM reply → {reply}")
                self.log_turn(
                    {"from": "GM", "content": prompt},
                    {"from": "Player 1", "content": reply},
                )
                m = self.PARSE.search(reply)
                drop_x = int(m.group(1))
                (
                    self.goal,
                    frames,
                    self.collisions,
                    self.steps_to_goal,
                    self.final_dist,
                    self.collision_points
                ) = self.env.simulate(drop_x)
                if getattr(self, "game_recorder", None):
                    summary = (
                        f"drop_x={drop_x}, "
                        f"collisions={self.collisions}, "
                        f"goal={self.goal}, "
                        f"steps={self.steps_to_goal}, "
                        f"dist={self.final_dist:.1f}"
                    )
                    self.game_recorder.log_event("GM", "GM", {"type": "sim_result", "content": summary})
                if self.goal:
                    break
                #making the collision points, clearer and structured
                collision_lines = [
                    f"{p['desc']}: ({round(p['x'], 1)}, {round(p['y'], 1)})"
                    for p in self.collision_points
                ]
                collisions_str = "\n".join(collision_lines)
                prompt = self.ref_prompt_t.format(
                    drop_x=drop_x,
                    collisions=collisions_str,
                    obstacles_str=self.env.obstacles,
                ) #updating the prompt for next turn with extra information.

            self.turns = turn_idx + 1
            self._on_after_game()

    def _on_after_game(self):
        self.log_key(m.METRIC_REQUEST_COUNT, self.turns)
        self.log_key(m.METRIC_SUCCESS,       int(self.goal))
        self.log_key(m.METRIC_LOSE,          int(not self.goal))
        self.log_key(m.METRIC_ABORTED,       0)
        self.log_key("Turns Used",           self.turns)

    def compute_episode_score(self) -> float:
            return 100.0 if getattr(self, 'goal', False) else 0.0

    def compute_turn_score(self, turn: int) -> float:
        return 100.0 if getattr(self, 'goal', False) else 0.0


    _advance_game        = lambda *a, **k: None
    _parse_response      = lambda *a, **k: None
    
class PhysicsPuzzleScorer(GameScorer):

    def score_rounds(self, interactions: Dict) -> None:
        for idx, turn in enumerate(interactions["turns"]):
            self.compute_round_score(idx, turn)

    def score_episode(self, interactions: Dict) -> None:
        if "meta" in interactions:
            self.scores[m.KEY_META] = interactions["meta"]
        if "players" in interactions:
            self.scores[m.KEY_PLAYERS] = interactions["players"]
        self.compute_episode_scores(interactions)

    def compute_episode_scores(self, interactions: Dict) -> None:
        turns_used = interactions.get("Turns Used")
        turns_used = int(turns_used)
        for key in (m.METRIC_SUCCESS, m.METRIC_LOSE, m.METRIC_ABORTED):
            if key in interactions:
                self.log_episode_score(key, interactions[key])
        success = bool(interactions.get(m.METRIC_SUCCESS, False))
        base          = 100 if success else 0
        turn_bonus    = max(0, 30 - turns_used) if success else 0  # max 30
        final_score   = min(100.0, round((base + turn_bonus) / 130 * 100, 2))

        self.log_episode_score(m.BENCH_SCORE, final_score)
        self.log_episode_score("Final Score (%)", final_score)
        self.log_episode_score("Turns Used", turns_used)

class PhysicsPuzzleBenchmark(GameBenchmark):
    def create_game_master(
        self,
        experiment: dict,
        player_models: List[backends.Model],
    ):
        return PhysicsPuzzleMaster(
            self.game_name,
            self.game_path,
            experiment,
            player_models,
        )

    def create_game_scorer(self, experiment: dict, game_instance: dict):
        return PhysicsPuzzleScorer(self.game_name, experiment, game_instance)

    def create_player(self, model: Model) -> Player:
        return BallDropper(model)
###############################################################################################################################################
#Set-ExecutionPolicy RemoteSigned -Scope CurrentUser
#.\venv\Scripts\Activate.ps1
#clem run -g en_mm_Physics-Puzzle -m gemini-1.5-flash
#clem run -g de_mm_Physics-Puzzle -m gemini-1.5-flash
#clem run -g en_textual_Physics-Puzzle -m gemini-1.5-flash
#clem run -g de_textual_Physics-Puzzle -m gemini-1.5-flash
#clem run -g sp_mm_Physics-Puzzle -m gemini-1.5-flash
#clem run -g sp_textual_Physics-Puzzle -m gemini-1.5-flash

#clem run -g en_mm_Physics-Puzzle -m gemma-3-27b
#clem run -g de_mm_Physics-Puzzle -m gemma-3-27b
#clem run -g en_textual_Physics-Puzzle -m gemma-3-27b
#clem run -g de_textual_Physics-Puzzle -m gemma-3-27b
#clem run -g sp_mm_Physics-Puzzle -m gemma-3-27b
#clem run -g sp_textual_Physics-Puzzle -m gemma-3-27b


#clem run -g en_mm_Physics-Puzzle -m mock
#clem run -g de_mm_Physics-Puzzle -m mock
#clem run -g en_textual_Physics-Puzzle -m mock
#clem run -g de_textual_Physics-Puzzle -m mock
###############################################################################################################################################
