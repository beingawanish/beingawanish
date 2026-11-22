package com.edacommerce.edacommon.ids;

import static org.assertj.core.api.Assertions.assertThat;

import java.util.ArrayList;
import java.util.List;
import java.util.UUID;
import org.junit.jupiter.api.Test;

class IdsTest {
  @Test
  void uuidV7LowerCaseTimeOrdered() {
    List<String> ids = new ArrayList<>();
    for (int i = 0; i < 1000; i++) {
      ids.add(Ids.newId());
    }
    for (String id : ids) {
      assertThat(id).matches("[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}");
      assertThat(UUID.fromString(id).version()).isEqualTo(7);
    }
    assertThat(ids).isSorted();
  }
}
