package com.edacommerce.edacommon.testing;

import java.io.IOException;
import java.io.InputStream;
import java.io.UncheckedIOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.stream.Stream;
import org.apache.avro.Schema;

/** Access to {@code contracts/} from tests: bundled schemas, golden examples, SQL, OpenAPI. */
public final class Contracts {
  private Contracts() {}

  public static Path dir() {
    String configured = System.getProperty("eda.contracts.dir");
    Path p = configured != null ? Path.of(configured) : Path.of("../../../contracts");
    if (!Files.isDirectory(p)) {
      throw new IllegalStateException("contracts directory not found: " + p.toAbsolutePath());
    }
    return p;
  }

  /** The bundled schema text exactly as registered by {@code make schemas}. */
  public static Schema bundledSchema(String fullName) {
    try (InputStream in =
        Contracts.class.getClassLoader().getResourceAsStream("avro-bundled/" + fullName + ".avsc")) {
      if (in == null) {
        return new Schema.Parser().parse(dir().resolve("avro-bundled/" + fullName + ".avsc").toFile());
      }
      return new Schema.Parser().parse(in);
    } catch (IOException e) {
      throw new UncheckedIOException(e);
    }
  }

  public static byte[] exampleBin(String fullName) {
    return read(dir().resolve("examples/" + fullName + ".bin"));
  }

  public static String exampleJson(String fullName) {
    return new String(read(dir().resolve("examples/" + fullName + ".json")), java.nio.charset.StandardCharsets.UTF_8);
  }

  /** Full names of every golden example. */
  public static List<String> exampleNames() {
    try (Stream<Path> files = Files.list(dir().resolve("examples"))) {
      return files
          .map(f -> f.getFileName().toString())
          .filter(n -> n.endsWith(".bin"))
          .map(n -> n.substring(0, n.length() - 4))
          .sorted()
          .toList();
    } catch (IOException e) {
      throw new UncheckedIOException(e);
    }
  }

  public static String commonTablesSql() {
    return new String(read(dir().resolve("sql/common-tables.sql")), java.nio.charset.StandardCharsets.UTF_8);
  }

  public static Path openApi(String file) {
    return dir().resolve("openapi/" + file);
  }

  private static byte[] read(Path p) {
    try {
      return Files.readAllBytes(p);
    } catch (IOException e) {
      throw new UncheckedIOException(e);
    }
  }
}
