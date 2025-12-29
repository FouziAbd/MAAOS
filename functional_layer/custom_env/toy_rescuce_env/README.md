# Toy Rescue Custom Environment

A cooperative multi-agent PettingZoo environment where 3 agents must find, retrieve, and deliver specific toys to a Drop Box in **Room 7**.

## Environment Details

### Grid & Rooms
- **Size**: 20x20 Grid.
- **Layout**: 8 distinct rooms divided by walls with doors.
- **Drop Zone**: Located in **Room 7** (Bottom Left, approx 5, 17). Agents must stand on the box to deliver toys.

### Agents
- **Count**: 3 Robots (`agent_0`, `agent_1`, `agent_2`).
- **Capabilities**: Move, Scan (LIDAR/Camera), Pick, Put.

## Toys & Spawning Logic
There are 4 unique toys. **Only one toy can appear per room.**

| Toy | Color | Shape | Reward | Requirements | Spawn Probability |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Toy 1** | Red | Round | +10 | 1 Agent | 90% Room 8, 10% Room 5 |
| **Toy 2** | Pink | Square| +50 | **2 Agents** | 70% Room 1, 20% Room 2, 10% Room 8 |
| **Toy 3** | Green | Rect | +5 | 1 Agent | 50% Room 5, 50% spread among others |
| **Toy 4** | Blue | Round | +15 | 1 Agent | 50% Room 4, 50% Room 6 |

## Actions & Costs

The agents have 8 discrete actions.

| ID | Action | Cost | Success Rate | Details |
| :--- | :--- | :--- | :--- | :--- |
| 0  | **Stay** | 0 | 100% | No effect. |
| 1-4 | **Move** (Up, Down, Left, Right) | -1 | 95% | Moves agent if space is empty. **Cooperation Rule**: If carrying the Pink Toy, both agents MUST move in the same direction, otherwise they stay put. |
| 5  | **Camera** | -5 | 80% | Reveals the specific ID (Color/Shape) of a toy in the 5x5 observation grid. Fails 20% of the time. |
| 6  | **Pick** | -1 (Success) / -4 (Fail) | 90% | Must be adjacent to a toy (distance <= 1). <br>**Pink Toy**: Two agents must attempt to pick it in the same turn. |
| 7  | **Put** | -1 (Success) / -3 (Fail) | 100% | Drops the toy. If in **Drop Zone (Room 7)**, generates Toy Reward. |

## Observation Space
Each agent sees a **5x5 local grid** (centered on themselves) with 6 channels:
1.  **Walls/Obstacles** (LIDAR - always on).
2.  **Other Agents**.
3.  **Generic Toy Presence** (Is there something there?).
4.  **Specific Toy ID** (Only visible if Camera action was successful).
5.  **Holding Status** (1 if self is holding a toy).
6.  **Drop Zone** (Visible if near Room 7 box).

## Goal
To maximize rewards, agents must:
1.  Navigate rooms to find toys based on probability hints.
2.  Use the Camera sparingly (high cost) to identify high-value targets (Pink).
3.  Coordinate to pick up the Pink Toy (simultaneous Pick action).
4.  Synchronize movement to carry the Pink Toy to Room 7.
5.  Deliver all toys to the box in Room 7.

