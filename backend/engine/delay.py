"""
Delay propagation (reactionary / knock-on delay) for FlightRotate.

This models what a real operations-control system does when a flight is delayed:
the aircraft keeps flying its planned rotation, and the delay ripples down that
aircraft's later legs, with each turnaround absorbing as much of it as the
schedule slack allows.

Method
------
For a given assignment (flight_id -> tail), each aircraft's flights are walked in
departure order. Starting from the primary delayed flight, the actual departure
of every leg is::

    actual_departure = max(
        scheduled_departure + (primary delay, only on the delayed flight),
        previous_actual_arrival + turnaround_at(this_leg.origin),
    )

so a leg can be pushed later either by its own injected delay or by a late
inbound aircraft. Flight durations are preserved (a delayed aircraft leaves and
arrives later by the same amount it is delayed). The turnaround uses the same
per-airport minimum turnaround the connection graph uses, defaulting to
DEFAULT_MIN_TURNAROUND where an airport-specific value is not supplied.

Only the delayed flight and its DOWNSTREAM same-aircraft legs can be affected;
upstream legs and other aircraft are untouched. This is a pure forward
simulation over a fixed plan -- it does not re-assign aircraft (that is the job
of the recovery re-optimization) and never mutates the input flights.

Scope: schedule perturbation only; there is no curfew/slot model, so a leg can
always be pushed later in time (it is never dropped here -- recovery, not
propagation, is where flights may become uncovered).
"""

from datetime import timedelta

from engine.graph_builder import DEFAULT_MIN_TURNAROUND


def _turnaround_minutes(origin, airport_turnarounds):
    """Minimum turnaround at `origin`, falling back to the default."""
    if airport_turnarounds:
        return airport_turnarounds.get(origin, DEFAULT_MIN_TURNAROUND)
    return DEFAULT_MIN_TURNAROUND


def propagate_delay(solution, flights_by_id, delayed_flight_id, delay_minutes,
                    airport_turnarounds=None):
    """
    Propagate a primary departure delay through the operating plan.

    Parameters
    ----------
    solution : dict           flight_id -> tail_number | None (the plan flown)
    flights_by_id : dict       flight_id -> Flight (with scheduled_departure,
                               scheduled_arrival, origin, destination, ...)
    delayed_flight_id : str    the flight receiving the primary delay
    delay_minutes : int        size of the primary delay (must be > 0)
    airport_turnarounds : dict optional {iata_code: min_turnaround_min}

    Returns
    -------
    dict with the delayed flight, the list of affected flights (primary first,
    then knock-on legs in time order, each with scheduled/actual departure and
    its total delay), and roll-up metrics. Raises ValueError if the flight is
    unknown, not in the plan, or the delay is not positive.
    """
    if delayed_flight_id not in flights_by_id:
        raise ValueError(f"Unknown flight_id: {delayed_flight_id}")
    if delay_minutes <= 0:
        raise ValueError("delay_minutes must be a positive number of minutes")
    if solution.get(delayed_flight_id) is None:
        raise ValueError(
            f"Flight {delayed_flight_id} is not assigned in the current plan; "
            "there is nothing to delay."
        )

    # Group the plan into per-aircraft rotations, ordered by departure.
    by_tail = {}
    for fid, tail in solution.items():
        if tail is None:
            continue
        by_tail.setdefault(tail, []).append(fid)
    for fids in by_tail.values():
        fids.sort(key=lambda f: flights_by_id[f].scheduled_departure)

    # Walk every rotation, carrying the running actual arrival forward. Only the
    # rotation containing the delayed flight can produce non-zero delays, but we
    # walk all of them uniformly; legs before the delayed one absorb nothing and
    # come out at zero delay.
    timings = {}  # fid -> (actual_dep, actual_arr, delay_min)
    for tail, fids in by_tail.items():
        prev_actual_arr = None
        for fid in fids:
            f = flights_by_id[fid]
            duration = f.scheduled_arrival - f.scheduled_departure
            earliest = f.scheduled_departure
            if prev_actual_arr is not None:
                turn = _turnaround_minutes(f.origin, airport_turnarounds)
                earliest = max(earliest, prev_actual_arr + timedelta(minutes=turn))
            injected = delay_minutes if fid == delayed_flight_id else 0
            actual_dep = max(
                earliest, f.scheduled_departure + timedelta(minutes=injected)
            )
            actual_arr = actual_dep + duration
            delay_min = round(
                (actual_dep - f.scheduled_departure).total_seconds() / 60
            )
            timings[fid] = (actual_dep, actual_arr, delay_min, tail)
            prev_actual_arr = actual_arr

    def _row(fid):
        f = flights_by_id[fid]
        actual_dep, actual_arr, delay_min, tail = timings[fid]
        return {
            "flight_id": fid,
            "flight_number": getattr(f, "flight_number", fid),
            "route": f"{f.origin}->{f.destination}",
            "tail_number": tail,
            "scheduled_departure": f.scheduled_departure.isoformat(),
            "actual_departure": actual_dep.isoformat(),
            "delay_minutes": delay_min,
        }

    primary = _row(delayed_flight_id)

    # Knock-on legs: same aircraft, after the delayed flight, with delay > 0.
    delayed_tail = solution[delayed_flight_id]
    delayed_dep = flights_by_id[delayed_flight_id].scheduled_departure
    knock_on = [
        _row(fid)
        for fid, (_, _, delay_min, tail) in timings.items()
        if tail == delayed_tail
        and fid != delayed_flight_id
        and flights_by_id[fid].scheduled_departure > delayed_dep
        and delay_min > 0
    ]
    knock_on.sort(key=lambda r: r["scheduled_departure"])

    total_reactionary = sum(r["delay_minutes"] for r in knock_on)
    max_delay = max([primary["delay_minutes"]] + [r["delay_minutes"] for r in knock_on])

    return {
        "delayed_flight": primary,
        "delay_minutes": delay_minutes,
        "affected": [primary] + knock_on,
        "knock_on_count": len(knock_on),
        "flights_delayed": 1 + len(knock_on),
        "total_reactionary_delay_min": total_reactionary,
        "total_delay_min": primary["delay_minutes"] + total_reactionary,
        "max_delay_min": max_delay,
    }
