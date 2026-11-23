package com.edacommerce.fulfilment.domain;

import java.time.Instant;
import java.util.ArrayList;
import java.util.EnumMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;

/**
 * A return the warehouse expects (ExpectReturn from the returns saga): EXPECTED -> RECEIVED (the
 * carrier delivered the return parcel) -> INSPECTED (one outcome per unit, grouped per line). Every
 * step happens at most once; repeats are ignored.
 */
public final class ReturnIntake {
  private final String returnId;
  private final String orderId;
  private final String rmaNumber;
  private IntakeStatus status;
  private final List<ReturnLine> lines;
  private final Instant expectedBy;
  private Instant receivedAt;
  private List<InspectionResult> results;
  private Instant inspectedAt;
  private long version;

  public ReturnIntake(
      String returnId,
      String orderId,
      String rmaNumber,
      IntakeStatus status,
      List<ReturnLine> lines,
      Instant expectedBy,
      Instant receivedAt,
      List<InspectionResult> results,
      Instant inspectedAt,
      long version) {
    this.returnId = returnId;
    this.orderId = orderId;
    this.rmaNumber = rmaNumber;
    this.status = status;
    this.lines = List.copyOf(lines);
    this.expectedBy = expectedBy;
    this.receivedAt = receivedAt;
    this.results = results == null ? List.of() : List.copyOf(results);
    this.inspectedAt = inspectedAt;
    this.version = version;
  }

  public static ReturnIntake expect(
      String returnId, String orderId, String rmaNumber, List<ReturnLine> lines, Instant by) {
    if (lines.isEmpty()) {
      throw new FulfilmentException("return " + returnId + " has no lines");
    }
    return new ReturnIntake(
        returnId, orderId, rmaNumber, IntakeStatus.EXPECTED, lines, by, null, null, null, 0);
  }

  /** The parcel arrived. Empty when already received (a duplicate delivery notice). */
  public Optional<Long> receive(Instant now) {
    if (status != IntakeStatus.EXPECTED) {
      return Optional.empty();
    }
    status = IntakeStatus.RECEIVED;
    receivedAt = now;
    return Optional.of(++version);
  }

  /**
   * Records the warehouse's per-unit outcomes. Units the warehouse did not report are MISSING.
   *
   * @return the new version, empty when the intake is not waiting for inspection
   */
  public Optional<Long> inspect(Map<String, List<InspectionOutcome>> unitOutcomes, Instant now) {
    if (status != IntakeStatus.RECEIVED) {
      return Optional.empty();
    }
    List<InspectionResult> grouped = new ArrayList<>();
    for (ReturnLine line : lines) {
      grouped.addAll(group(line, unitOutcomes.getOrDefault(line.lineId(), List.of())));
    }
    results = List.copyOf(grouped);
    status = IntakeStatus.INSPECTED;
    inspectedAt = now;
    return Optional.of(++version);
  }

  /** One result per (line, outcome) in a stable order (RESTOCKABLE, DAMAGED, MISSING). */
  public static List<InspectionResult> group(ReturnLine line, List<InspectionOutcome> outcomes) {
    Map<InspectionOutcome, Integer> counts = new EnumMap<>(InspectionOutcome.class);
    int seen = 0;
    for (InspectionOutcome o : outcomes) {
      if (seen == line.quantity()) {
        break;
      }
      counts.merge(o, 1, Integer::sum);
      seen++;
    }
    if (seen < line.quantity()) {
      counts.merge(InspectionOutcome.MISSING, line.quantity() - seen, Integer::sum);
    }
    List<InspectionResult> out = new ArrayList<>();
    for (InspectionOutcome o : InspectionOutcome.values()) {
      Integer q = counts.get(o);
      if (q != null && q > 0) {
        out.add(new InspectionResult(line.lineId(), line.sku(), q, o, null));
      }
    }
    return out;
  }

  public String returnId() {
    return returnId;
  }

  public String orderId() {
    return orderId;
  }

  public String rmaNumber() {
    return rmaNumber;
  }

  public IntakeStatus status() {
    return status;
  }

  public List<ReturnLine> lines() {
    return lines;
  }

  public Instant expectedBy() {
    return expectedBy;
  }

  public Instant receivedAt() {
    return receivedAt;
  }

  public List<InspectionResult> results() {
    return results;
  }

  public Instant inspectedAt() {
    return inspectedAt;
  }

  public long version() {
    return version;
  }
}
