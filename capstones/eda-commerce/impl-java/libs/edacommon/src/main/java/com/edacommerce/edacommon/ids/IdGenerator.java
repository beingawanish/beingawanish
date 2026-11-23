package com.edacommerce.edacommon.ids;

/** Injectable id source, so tests can use deterministic ids. The default is {@link Ids#newId()}. */
@FunctionalInterface
public interface IdGenerator {
  String newId();

  static IdGenerator uuidV7() {
    return Ids::newId;
  }
}
