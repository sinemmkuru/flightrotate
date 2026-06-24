"""
Main genetic algorithm loop for the aircraft rotation problem.

Combines the components built earlier:
  - population.py         : builds the initial population
  - solution.py           : evaluates fitness of a solution
  - genetic_operators.py  : selection, crossover, mutation
  - graph_builder.py      : the FCG used by all of the above

The algorithm runs for a fixed number of generations. In each generation:
  1. Evaluate fitness for every individual
  2. Keep the best K individuals unchanged (elitism)
  3. Fill the rest of the new population via selection -> crossover ->
     mutation
  4. Record the best fitness so far (convergence tracking)

A GAResult object is returned containing the best solution, its fitness
breakdown, and the per-generation convergence history (used for the
fitness-over-generations chart in the thesis).
"""

import time
from dataclasses import dataclass, field
from typing import Optional, Callable

from engine.population import build_initial_population
from engine.solution import (
    evaluate_solution, FitnessBreakdown, DEFAULT_WEIGHTS, build_aircraft_caps,
)
from engine.genetic_operators import tournament_select, crossover, mutate

# -------------------------------------
# DEFAULT_GA_PARAMS — varsayılan parametreler. 
#Population 100, generations 200, tournament size 3, elitism 5, mutation rate 0.15. 
#Mutation rate'i normalden yüksek tuttuk (0.15) 
#çünkü bizim mutasyon operatörlerimiz FCG kısıtlarına takılıp sessizce başarısız olabilir; 
#tetiklenme olasılığını artırarak gerçekten gerçekleşen mutasyon sayısını dengeliyoruz. 
#----------------------------------------
# Default GA hyperparameters (compiled from our design discussions).
# These can be overridden by the caller.
DEFAULT_GA_PARAMS = {
    "population_size": 100,
    "generations": 200,
    "tournament_size": 3,
    "elitism_count": 5,        # top K individuals carried over unchanged
    "mutation_rate": 0.15,     # higher than typical because mutations
                                # often fail silently when FCG-infeasible
}


@dataclass
class GAResult:
    """The full result of a GA run, including convergence history."""
    best_solution: dict                       # flight_id -> tail_number | None
    best_fitness: FitnessBreakdown            # detailed breakdown of best
    convergence: list[float] = field(default_factory=list)
                                               # best fitness per generation
    avg_per_generation: list[float] = field(default_factory=list)
                                               # population avg per generation
    elapsed_seconds: float = 0.0
    generations_run: int = 0

#----------------------------------------
# run_genetic_algorithm — GA'yı başlatan ana fonksiyon. 
#Her generation'da fitness değerlerini hesaplar, en iyi bireyi takip eder. 
#Population'ın ortalama fitness'ini kaydeder ve WebSocket ile güncellemeler sağlar.
#----------------------------------------

def run_genetic_algorithm(
    #----------------------------------------
    #----------------------------------------
    flights: list,
    aircraft_list: list,
    graph,
    weights: Optional[dict] = None,
    params: Optional[dict] = None,
    seed: Optional[int] = None,
    progress_callback: Optional[Callable[[int, float], None]] = None,
    aircraft_starts: Optional[dict] = None,
) -> GAResult:
    """
    Runs the genetic algorithm and returns the best solution found.

    Parameters:
        flights: list of Flight ORM objects
        aircraft_list: list of Aircraft ORM objects
        graph: the Flight Connection Graph (networkx DiGraph)
        weights: objective weights dict (defaults to DEFAULT_WEIGHTS)
        params: GA hyperparameters dict (defaults to DEFAULT_GA_PARAMS)
        seed: optional random seed for reproducible runs
        progress_callback: optional fn(generation, best_fitness) called
                           after each generation (used later for WebSocket
                           progress streaming)

    Returns:
        A GAResult with the best solution, its detailed fitness, and the
        convergence history.
    """
    if weights is None:
        weights = DEFAULT_WEIGHTS
    if params is None:
        params = DEFAULT_GA_PARAMS

    flights_by_id = {f.flight_id: f for f in flights}
    # Aircraft availability / maintenance capabilities, built once and reused
    # for every fitness evaluation below.
    aircraft_caps = build_aircraft_caps(aircraft_list)
    start_time = time.time()

    # --- Step 1: build the initial population ---
    population = build_initial_population(
        population_size=params["population_size"],
        aircraft_list=aircraft_list,
        flights_by_id=flights_by_id,
        graph=graph,
        seed=seed,
        aircraft_starts=aircraft_starts,
    )

    # Track the best solution ever seen across all generations
    best_solution_so_far: Optional[dict] = None
    best_breakdown_so_far: Optional[FitnessBreakdown] = None

    convergence: list[float] = []
    avg_history: list[float] = []

    # --- Step 2: generational loop ---
    for gen in range(params["generations"]):
        # Evaluate fitness for everyone in this generation
        breakdowns = [
            evaluate_solution(
                sol, flights_by_id, graph, weights, aircraft_caps, aircraft_starts
            )
            for sol in population
        ]
        scores = [b.fitness for b in breakdowns]

        # Track the best individual of this generation
        best_idx = max(range(len(scores)), key=lambda i: scores[i])
        gen_best_fitness = scores[best_idx]
        gen_avg_fitness = sum(scores) / len(scores)

        convergence.append(gen_best_fitness)
        avg_history.append(gen_avg_fitness)

        # Update overall best
        if (
            best_breakdown_so_far is None
            or gen_best_fitness > best_breakdown_so_far.fitness
        ):
            best_solution_so_far = dict(population[best_idx])
            best_breakdown_so_far = breakdowns[best_idx]

        # Notify progress watcher if any
        if progress_callback is not None:
            progress_callback(gen, gen_best_fitness)

        # --- Step 3: build the next generation ---
        # Elitism: carry the top K individuals unchanged
        ranked_indices = sorted(
            range(len(scores)), key=lambda i: scores[i], reverse=True
        )
        elite_count = params["elitism_count"]
        new_population = [dict(population[i]) for i in ranked_indices[:elite_count]]

        # Fill the rest with offspring
        while len(new_population) < params["population_size"]:
            parent_a = tournament_select(
                population, scores, params["tournament_size"]
            )
            parent_b = tournament_select(
                population, scores, params["tournament_size"]
            )
            child = crossover(parent_a, parent_b, graph, flights_by_id)
            child = mutate(
                child, graph, flights_by_id, aircraft_list,
                params["mutation_rate"], aircraft_starts,
            )
            new_population.append(child)

        population = new_population

    elapsed = time.time() - start_time

    return GAResult(
        best_solution=best_solution_so_far,
        best_fitness=best_breakdown_so_far,
        convergence=convergence,
        avg_per_generation=avg_history,
        elapsed_seconds=elapsed,
        generations_run=params["generations"],
    )
    #------------------
    #GAResult dataclass'ı — sadece en iyi çözümü değil, convergence geçmişini de tutar. 
    #Bu, tezin Chapter 6'sındaki "fitness-over-generations" grafiği için kritik. 
    #Her generation'da hem en iyi fitness hem population ortalaması kaydediliyor 
    #— bu ikisi arasındaki yakınlaşma "GA gerçekten yakınsıyor mu?" sorusuna cevap verir.
    #-------------------