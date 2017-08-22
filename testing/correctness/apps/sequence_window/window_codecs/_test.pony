use "buffered"
use "collections"
use "sendence/connemara"

actor Main is TestList
  new create(env: Env) =>
    Connemara(env, this)

  new make() => None

  fun tag tests(test: Connemara) =>
    test(_TestWindowEncoder)
    test(_TestWindowDecoder)
    test(_TestWindowState)

class iso _TestWindowEncoder is UnitTest
  fun name(): String => "window_codecs/WindowEncoder"

  fun apply(h: TestHelper) ? =>
    let s = "[1,2,3,4]"
    let byteseqs = WindowEncoder(s)
    let encoded = match byteseqs(1)
    | let m: String val => m
    | let m: Array[U8] val => String.from_array(m)
    else ""
    end
    h.assert_eq[String]("[1,2,3,4]", encoded)

class iso _TestWindowDecoder is UnitTest
  fun name(): String => "window_codecs/WindowDecoder"

  fun apply(h: TestHelper) ? =>
    let s: String val = "[1,2,3,4]"
    let decoded: Array[U64] val = WindowU64Decoder(s)
    h.assert_eq[U64](1, decoded(0))
    h.assert_eq[U64](2, decoded(1))
    h.assert_eq[U64](3, decoded(2))
    h.assert_eq[U64](4, decoded(3))

class iso _TestWindowState is UnitTest
  fun name(): String => "window_codecs/WindowState"

  fun apply(h: TestHelper) ? =>
    let out_writer: Writer = Writer
    let last_value: U64 = 55

    WindowStateEncoder(last_value, out_writer)
    let byteseqs: Array[ByteSeq] val = out_writer.done()
    let s = recover Array[U8] end
    for bs in byteseqs.values() do
      s.append(bs)
    end
    // Expecting: 1xU64
    h.assert_eq[USize](8, s.size())

    // Decode
    let in_reader: Reader = Reader
    in_reader.append(consume s)
    let decoded_value: U64 = WindowStateDecoder(in_reader)
    h.assert_eq[U64](last_value, decoded_value)
