"""Small-budget implementations of the four XGBoost tuners used by Gao et al."""

from __future__ import annotations

from collections.abc import Callable

import numpy as np


def run_optimizer(
    method: str,
    objective: Callable[[np.ndarray], float],
    *,
    population_size: int = 6,
    generations: int = 2,
    seed: int = 42,
) -> dict:
    """Optimize a normalized four-parameter vector using GA, PSO, WOA, or GWO.

    The search mechanics follow each named population method. Search budgets are
    deliberately configurable and smaller than the paper's 20-100 population,
    200 iteration experiments so the project can run on a student laptop.
    """
    name = method.upper()
    if name not in {"GA", "PSO", "WOA", "GWO"}:
        raise ValueError(f"Unknown optimizer: {method}")
    if population_size < 4 or generations < 1:
        raise ValueError("population_size must be >= 4 and generations >= 1")

    rng = np.random.default_rng(seed)
    dim = 4
    positions = rng.uniform(0.0, 1.0, size=(population_size, dim))
    velocities = rng.uniform(-0.1, 0.1, size=(population_size, dim))
    fitness_cache: dict[tuple[float, ...], float] = {}
    evaluations = 0

    def score(position: np.ndarray) -> float:
        nonlocal evaluations
        clipped = np.clip(position, 0.0, 1.0)
        key = tuple(np.round(clipped, 5))
        if key not in fitness_cache:
            fitness_cache[key] = float(objective(clipped))
            evaluations += 1
        return fitness_cache[key]

    fitness = np.array([score(p) for p in positions])
    personal_positions = positions.copy()
    personal_fitness = fitness.copy()
    history = [float(fitness.min())]

    for generation in range(generations):
        order = np.argsort(fitness)
        if name == "GA":
            # Keep the two best chromosomes; tournament selection, uniform
            # crossover and Gaussian mutation form the next population.
            children = [positions[order[0]].copy(), positions[order[1]].copy()]
            while len(children) < population_size:
                def tournament() -> np.ndarray:
                    picks = rng.integers(0, population_size, size=3)
                    return positions[picks[np.argmin(fitness[picks])]]
                a, b = tournament(), tournament()
                mask = rng.random(dim) < 0.5
                child = np.where(mask, a, b)
                mutate = rng.random(dim) < 0.25
                child[mutate] += rng.normal(0, 0.18, size=int(mutate.sum()))
                children.append(np.clip(child, 0, 1))
            positions = np.asarray(children)
        elif name == "PSO":
            global_best = positions[order[0]].copy()
            r1, r2 = rng.random((2, population_size, dim))
            velocities = (0.65 * velocities + 1.5 * r1 * (personal_positions - positions)
                          + 1.5 * r2 * (global_best - positions))
            positions = np.clip(positions + velocities, 0, 1)
        elif name == "WOA":
            leader = positions[order[0]].copy()
            a = 2.0 - 2.0 * generation / max(generations, 1)
            for i in range(population_size):
                r1, r2 = rng.random(), rng.random()
                A, C = 2 * a * r1 - a, 2 * r2
                if rng.random() < 0.5:
                    if abs(A) < 1:
                        ref = leader
                    else:
                        ref = positions[rng.integers(population_size)]
                    D = abs(C * ref - positions[i])
                    positions[i] = ref - A * D
                else:
                    distance = abs(leader - positions[i])
                    positions[i] = distance * np.exp(1.0 * rng.uniform(-1, 1)) * np.cos(2 * np.pi * rng.random()) + leader
            positions = np.clip(positions, 0, 1)
        else:  # GWO
            alpha, beta, delta = positions[order[:3]].copy()
            a = 2.0 - 2.0 * generation / max(generations, 1)
            updated = []
            for current in positions:
                guides = []
                for leader in (alpha, beta, delta):
                    A = 2 * a * rng.random(dim) - a
                    C = 2 * rng.random(dim)
                    guides.append(leader - A * abs(C * leader - current))
                updated.append(np.mean(guides, axis=0))
            positions = np.clip(np.asarray(updated), 0, 1)

        fitness = np.array([score(p) for p in positions])
        improved = fitness < personal_fitness
        personal_positions[improved] = positions[improved]
        personal_fitness[improved] = fitness[improved]
        history.append(float(fitness.min()))

    best_index = int(np.argmin(fitness))
    best = positions[best_index].copy()
    best_score = float(fitness[best_index])
    if personal_fitness.min() < best_score:
        best_index = int(np.argmin(personal_fitness))
        best = personal_positions[best_index].copy()
        best_score = float(personal_fitness[best_index])
    return {"method": name, "best_position": best, "best_fitness": best_score,
            "history": history, "evaluations": evaluations,
            "population_size": population_size, "generations": generations}
