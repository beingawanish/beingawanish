package com.edacommerce.edacommon.consumer;

import java.util.List;

/**
 * Several handlers declared as one bean (for services with many small mappings, such as an
 * orchestrator listening to every participant's replies). The runtime registers each of them.
 */
@FunctionalInterface
public interface MessageHandlerGroup {
  List<MessageHandler<?>> handlers();

  /** All handlers from single-handler beans and groups. */
  static List<MessageHandler<?>> collect(
      List<MessageHandler<?>> singles, List<MessageHandlerGroup> groups) {
    List<MessageHandler<?>> all = new java.util.ArrayList<>(singles);
    groups.forEach(g -> all.addAll(g.handlers()));
    return all;
  }
}
