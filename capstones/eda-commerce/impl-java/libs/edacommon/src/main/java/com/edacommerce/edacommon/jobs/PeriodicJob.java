package com.edacommerce.edacommon.jobs;

import java.time.Duration;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.context.SmartLifecycle;

/**
 * A background loop (relay, sweeper, housekeeping, reconciliation) with fixed delay between runs.
 * Failures are logged and the next run proceeds; shutdown lets the current run finish.
 */
public class PeriodicJob implements SmartLifecycle {
  private static final Logger log = LoggerFactory.getLogger(PeriodicJob.class);

  private final String name;
  private final Duration interval;
  private final Runnable task;
  private ScheduledExecutorService executor;
  private volatile boolean running;

  public PeriodicJob(String name, Duration interval, Runnable task) {
    this.name = name;
    this.interval = interval;
    this.task = task;
  }

  @Override
  public synchronized void start() {
    if (running) {
      return;
    }
    executor =
        Executors.newSingleThreadScheduledExecutor(
            Thread.ofPlatform().name(name).daemon().factory());
    var unused =
        executor.scheduleWithFixedDelay(
            this::runSafely, interval.toMillis(), interval.toMillis(), TimeUnit.MILLISECONDS);
    running = true;
  }

  private void runSafely() {
    try {
      task.run();
    } catch (RuntimeException e) {
      log.warn("job {} failed; retrying in {}", name, interval, e);
    }
  }

  @Override
  public synchronized void stop() {
    if (!running) {
      return;
    }
    running = false;
    executor.shutdown();
    try {
      if (!executor.awaitTermination(20, TimeUnit.SECONDS)) {
        executor.shutdownNow();
      }
    } catch (InterruptedException e) {
      Thread.currentThread().interrupt();
      executor.shutdownNow();
    }
  }

  @Override
  public boolean isRunning() {
    return running;
  }

  public String name() {
    return name;
  }
}
