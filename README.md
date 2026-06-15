# Multi-Agent LLM-Driven System (ma_aos)

## Project Goal

Create an instantiation of a multi-agent system where:
- **Multiple agents** collaborate in a coordinated environment
- **LLMs** drive the core decision-making and reasoning components
- **Belief state representation** is precise and well-structured to support agent reasoning and planning

## System Architecture

### Layers

1. **Functional Layer** - Environment definitions and RL-based agents
   - Custom environments (toy_rescue_env)
   - Agent implementations (KAZ, KAZ_RL, KAZ_RL_LLM_Agents)

2. **Middleware Layer** - Action and observation processing
   - Action descriptor & executor
   - Observation simplifier & scenario simplifier
   - Orchestration logic

3. **Model Layer** - Agent intelligence and knowledge management
   - Agent models with LLM-driven planning
   - Belief state management for precise state tracking
   - Reward management and skill integration

4. **UI Layer** - User interface and visualization