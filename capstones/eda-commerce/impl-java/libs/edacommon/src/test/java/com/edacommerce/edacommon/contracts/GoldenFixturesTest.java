package com.edacommerce.edacommon.contracts;

import static org.assertj.core.api.Assertions.assertThat;

import com.edacommerce.edacommon.testing.Contracts;
import com.edacommerce.edacommon.testing.GoldenFixtures;
import java.util.List;
import java.util.stream.Stream;
import org.apache.avro.specific.SpecificRecord;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.MethodSource;

/**
 * Day 1 acceptance: every golden example decodes with our Avro code to its .json, and encoding the
 * .json reproduces the bytes, both with generic records and with the generated SpecificRecord classes.
 */
class GoldenFixturesTest {

  static Stream<String> examples() {
    return Contracts.exampleNames().stream();
  }

  @Test
  void everyContractMessageHasAGoldenExample() {
    List<String> names = Contracts.exampleNames();
    assertThat(names).hasSize(54);
  }

  @ParameterizedTest(name = "{0}")
  @MethodSource("examples")
  void genericRoundTrip(String fullName) {
    GoldenFixtures.assertGenericRoundTrip(fullName);
  }

  @ParameterizedTest(name = "{0}")
  @MethodSource("examples")
  void specificRoundTrip(String fullName) throws ClassNotFoundException {
    Class<? extends SpecificRecord> type = Class.forName(fullName).asSubclass(SpecificRecord.class);
    SpecificRecord record = GoldenFixtures.assertSpecificRoundTrip(type);
    GoldenFixtures.assertValidAgainstBundled(record);
  }
}
