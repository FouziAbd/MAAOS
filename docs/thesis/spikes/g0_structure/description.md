COOPERATIVE DOOR, PARTIALLY OBSERVABLE  (sole input for model generation)

Two agents, A and B, start in a corridor (the "hall"), A at the left end and B at the right end.
A heavy door in the corridor wall leads to a goal room. Two handle cells lie in the corridor,
handle_left and handle_right, one on each side of the door. The team succeeds when both agents
are in the goal room.

Skills (the executive runs exactly one skill per decision cycle):
  Goto(agent, place): walk to a handle, place in {handle_left, handle_right}. A handle holds one
    agent at a time, and an agent never "goes" to the handle it already holds. The corridor is
    one cell wide: A cannot get past B to handle_right while B holds handle_left, and B cannot
    get past A to handle_left while A holds handle_right; such a Goto fails and the agent stays.
  Enter(agent, door): walk through the open door into the goal room. Only possible while the
    door is open. An agent in the goal room stays there.
  CooperateOpen(agent, door, partner): the agent on handle_left and the partner on handle_right
    pull together. The door opens only if it is closed and not jammed. Even a free door does not
    always open: the joint pull sometimes slips and nothing happens.
  ClearJam(agent, place, door): the agent standing on handle `place` shakes the closed door.
    Shaking sometimes frees a jammed door, and never jams a free one. The shaking agent then
    feels a rattle that usually, but not always, tells the truth about whether the door is still
    jammed afterwards.

Hidden: whether the door starts jammed is decided at random at the start of each episode and is
never shown directly. A failed pull looks the same whether a jam or a slip caused it.

Observed after every skill: where each agent is (a handle, the goal room, or the hall), whether
the door is open, the skill's status (ok | fail; ClearJam reports ok whenever the shake was
performed), and after ClearJam the rattle reading (rattle_jam | rattle_free).

Rewards: -0.01 per agent per cycle, an extra -0.05 per shake, +1 per agent when both reach the
goal room. Discount 0.95.

The probabilities of the jam, the slip, the shake freeing the door and the rattle telling the
truth are NOT given: model each one as a named parameter.
