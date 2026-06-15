# Cooperative Search transport

## Core idea
A team of agents moves in a partially observable grid world.
Their goal is to find target objects and deliver them to a delivery zone.

Some objects can be moved by one agent, while others require multiple agents to cooperate.

The environment itself does not contain:
- belief state
- communication reasoning
- LLM logic
- planning logic

## World definition

### Grid
The world is a 2D grid.

Each cell can contain one of the following:

- empty space
- wall
- door or passage
- delivery zone
- object
- agent
- Map structure

The environment should support maps with:

- multiple rooms
- corridors between rooms
- open areas
- bottlenecks

For the first version, use a simple room-based layout:

- 5 rooms
- connected by doors/corridors
- one delivery zone

> **Later you can make this random.**

### Delivery zone

There is one special area where target objects must be delivered. a small 2x2 zone

## Agents
### Number of agents

The environment must support arbitrary N >= 2.

For debugging:

- start with 2 agents

For real experiments:

- support 4, 5, 6, and more

### Agent state

Each agent has:

- agent_id
- position = (x, y)
- direction
- carrying = None or object_id
- active = True/False
- optional later:
    - capability profile
    - strength
    - sensor type
### Agent roles

For v1, keep all agents identical.

Later, we can support heterogeneous roles such as:

- scout
- carrier
- inspector
- opener

