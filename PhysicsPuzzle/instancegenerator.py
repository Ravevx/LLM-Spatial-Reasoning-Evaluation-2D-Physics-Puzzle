import json
import os
import math
import random
import argparse
from pathlib import Path
from typing import Dict, List, Tuple

from clemcore.clemgame import GameInstanceGenerator

# Game and level config
WIDTH, HEIGHT = 600, 600
FPS = 60
MAX_TURNS = 2
N_LEVELS = 5
GAMES_PER_LEVEL = 2
X_MIN, X_MAX = 100, 500
Y_MIN, Y_MAX = 150, 400
MID_X, MID_Y = 300, 300
MAX_OBS_LEN = 350


class PhysicsPuzzleGameInstanceGenerator(GameInstanceGenerator):
   def __init__(self,filename: str):
       super().__init__(os.path.dirname(__file__))
       self.filename = filename
       self.generated_instances = []

   

   def on_generate(self):
    # Load prompt templates

    if "_de" in self.filename:
     mm_initial = self.load_template("resources/initial_prompt_mmde.txt")
     mm_refined = self.load_template("resources/refined_prompt_mmde.txt")
     tex_initial = self.load_template("resources/initial_prompt_texde.txt")
     tex_refined = self.load_template("resources/refined_prompt_texde.txt")

    elif "_sp" in self.filename:
     mm_initial = self.load_template("resources/initial_prompt_mmsp.txt")
     mm_refined = self.load_template("resources/refined_prompt_mmsp.txt")
     tex_initial = self.load_template("resources/initial_prompt_texsp.txt")
     tex_refined = self.load_template("resources/refined_prompt_texsp.txt")

    else:
     mm_initial = self.load_template("resources/initial_prompt_mm.txt")
     mm_refined = self.load_template("resources/refined_prompt_mm.txt")
     tex_initial = self.load_template("resources/initial_prompt_tex.txt")
     tex_refined = self.load_template("resources/refined_prompt_tex.txt")


    self.generated_instances_mm = {"experiments": []}
    self.generated_instances_textual = {"experiments": []}

    for level_idx in range(1, N_LEVELS + 1):
        level_name = f"level_{level_idx}"
        mm_config = {
            "width": WIDTH,
            "height": HEIGHT,
            "fps": FPS,
            "regex": "s*(\d{3})|\b(\d{3})\b",
            "max_turns": MAX_TURNS,
            "mode": "multimodal",
            "initial_prompt": mm_initial,
            "refined_prompt": mm_refined

            
        }

        textual_config = {
            "width": WIDTH,
            "height": HEIGHT,
            "fps": FPS,
            "regex": "s*(\d{3})|\b(\d{3})\b",
            "max_turns": MAX_TURNS,
            "mode": "textual",
            "initial_prompt": tex_initial,
            "refined_prompt": tex_refined
                
        }

        mm_instances = []
        textual_instances = []

        for game_idx in range(GAMES_PER_LEVEL):
            game_id = f"L{level_idx}_G{game_idx + 1}"
            obstacles = [self.build_midpoint_obstacle(1)]
            for i in range(2, level_idx + 1):
                obstacles.append(self.build_random_obstacle(i))

            mm_instances.append({
                "game_id": game_id,
                "obstacles": obstacles,
               
            })

            textual_instances.append({
                "game_id": game_id,
                "obstacles": obstacles,
            })

        # Append per level
        self.generated_instances_mm["experiments"].append({
            "name": level_name,
            "config": mm_config,
            "game_instances": mm_instances
        })

        self.generated_instances_textual["experiments"].append({
            "name": level_name,
            "config": textual_config,
            "game_instances": textual_instances
        })


   def generate_instances(self) -> List[Dict]:
       self.generate()  # runs on_generate
       return self.generated_instances_mm, self.generated_instances_textual  
        
   def random_point(self) -> Tuple[int, int]:
       while True:
           x, y = random.randint(X_MIN, X_MAX), random.randint(Y_MIN, Y_MAX)
           if (x, y) != (MID_X, MID_Y):
               return x, y


   def distance(self, p1: Tuple[int, int], p2: Tuple[int, int]) -> float:
       return math.hypot(p1[0] - p2[0], p1[1] - p2[1])


   def opposite_point(self, px: int, py: int) -> Tuple[int, int]:
       return 2 * MID_X - px, 2 * MID_Y - py


   def build_midpoint_obstacle(self, idx: int) -> Dict:
       while True:
           sx, sy = self.random_point()
           ex, ey = self.opposite_point(sx, sy)
           if (
               X_MIN <= ex <= X_MAX
               and Y_MIN <= ey <= Y_MAX
               and self.distance((sx, sy), (ex, ey)) <= MAX_OBS_LEN
               and (ex, ey) != (MID_X, MID_Y)
           ):
               break
       return {
           "obstacle_id": f"wall_{idx}",
           "start_point": [sx, sy],
           "end_point": [ex, ey],
           "thickness": 5,
           "description": "Segment with midpoint fixed at (300,300)",
       }


   def build_random_obstacle(self, idx: int) -> Dict:
       while True:
           sx, sy = self.random_point()
           ex, ey = self.random_point()
           if self.distance((sx, sy), (ex, ey)) <= MAX_OBS_LEN:
               break
       return {
           "obstacle_id": f"wall_{idx}",
           "start_point": [sx, sy],
           "end_point": [ex, ey],
           "thickness": 5,
       }


   def build_game_instance(self, level_idx: int, instance_idx: int, initial_prompt: str, refined_prompt: str) -> Dict:
       obstacles: List[Dict] = [self.build_midpoint_obstacle(1)]
       for i in range(2, level_idx + 1):
           obstacles.append(self.build_random_obstacle(i))
       game_id = f"L{level_idx}_G{instance_idx}"
       return {
           "game_id": game_id,
           "obstacles": obstacles,
           "initial_prompt": initial_prompt,
           "refined_prompt": refined_prompt,
           "initial_promptt": textual_initial_prompt,
           "refined_promptt": textual_refined_prompt
       }


if __name__ == "__main__":
   
    parser = argparse.ArgumentParser()
    parser.add_argument("--lang", type=str, choices=["en", "de" , "sp"], required=True, help="Language: en, de, or sp")
    args = parser.parse_args()

    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    IN_FOLDER = os.path.join(BASE_DIR, "in")
    os.makedirs(IN_FOLDER, exist_ok=True)

    # Save language-specific file
    lang_filename = f"instances_{args.lang}.json"
    lang_out_path = os.path.join(IN_FOLDER, lang_filename)

    # Also save to generic instances.json
    generic_out_path = os.path.join(IN_FOLDER, "instances.json")

    # Generate and save
    generator = PhysicsPuzzleGameInstanceGenerator(lang_out_path)
    mm_data, textual_data = generator.generate_instances()
    
    # Save multimodal
    mm_filename = f"instances_{args.lang}_mm.json"
    mm_path = os.path.join(IN_FOLDER, mm_filename)
    with open(mm_path, "w", encoding="utf-8") as f:
      json.dump(mm_data, f, indent=2, ensure_ascii=False)
    print(f"Saved multimodal instances to {mm_path}")
    
    # Save textual
    textual_filename = f"instances_{args.lang}_textual.json"
    textual_path = os.path.join(IN_FOLDER, textual_filename)
    with open(textual_path, "w", encoding="utf-8") as f:
      json.dump(textual_data, f, indent=2, ensure_ascii=False)
    print(f"Saved textual instances to {textual_path}")

    # Save language-specific file
    #generic_out_path = os.path.join(IN_FOLDER, "instances.json")
    with open(lang_out_path, "w", encoding="utf-8") as f:
        json.dump(generator.generated_instances, f, indent=2)
    print(f"Saved {args.lang.upper()} instances to {lang_out_path}")

    # Save same data to generic instances.json
    with open(generic_out_path, "w", encoding="utf-8") as f:
        json.dump(generator.generated_instances, f, indent=2)
    print(f"Also saved current run to {generic_out_path}")

#PhysicsPuzzleGameInstanceGenerator(args.out).generate()
