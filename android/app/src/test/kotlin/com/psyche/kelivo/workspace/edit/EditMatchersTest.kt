package com.psyche.kelivo.workspace.edit

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class EditMatchersTest {

    @Test fun exactReplacesUniqueOccurrence() {
        val result = EditMatchers.applyEdit("hello world", "world", "there")
        assertTrue(result is EditApplied)
        val applied = result as EditApplied
        assertEquals("hello there", applied.updated)
        assertEquals(1, applied.replacements)
        assertEquals(EditStrategy.EXACT, applied.strategy)
    }

    @Test fun exactReplaceAllReplacesEveryNonOverlappingMatch() {
        val result = EditMatchers.applyEdit("foo foo foo", "foo", "bar", replaceAll = true)
        val applied = result as EditApplied
        assertEquals("bar bar bar", applied.updated)
        assertEquals(3, applied.replacements)
        assertEquals(EditStrategy.EXACT, applied.strategy)
    }

    @Test fun exactAmbiguousWithoutReplaceAll() {
        val result = EditMatchers.applyEdit("foo foo", "foo", "bar")
        assertTrue(result is EditFailed)
        val failed = result as EditFailed
        assertTrue(failed.failure is EditAmbiguous)
        val ambiguous = failed.failure as EditAmbiguous
        assertEquals(2, ambiguous.count)
        assertEquals(EditStrategy.EXACT, ambiguous.strategy)
        assertEquals(
            "old_string matches 2 locations (strategy: exact); " +
                "add more surrounding context to make it unique, or set replace_all=true",
            failed.message,
        )
    }

    @Test fun lineTrimmedMatchesTrimmedLinesAndReindents() {
        val original = "void main() {\n    foo();\n    bar();\n}\n"
        val result = EditMatchers.applyEdit(original, "  foo();\n  bar();", "  foo();\n  baz();")
        val applied = result as EditApplied
        assertEquals(EditStrategy.LINE_TRIMMED, applied.strategy)
        assertEquals("void main() {\n    foo();\n    baz();\n}\n", applied.updated)
        assertEquals(1, applied.replacements)
    }

    @Test fun lineTrimmedIsDisabledWhenOldTextIsOnlyBlankLines() {
        val result = EditMatchers.applyEdit("a\n\n\nb\n", "  \n  \n", "x\n")
        assertTrue(result is EditFailed)
        assertTrue((result as EditFailed).failure is EditNotFound)
        assertEquals(EDIT_NOT_FOUND_MESSAGE, result.message)
    }

    @Test fun lineTrimmedReplaceAllOnIndentedCopies() {
        val result = EditMatchers.applyEdit(
            "    a\n    b\n    a\n    b\n", "a\nb", "c\nd", replaceAll = true,
        )
        val applied = result as EditApplied
        assertEquals(EditStrategy.LINE_TRIMMED, applied.strategy)
        assertEquals(2, applied.replacements)
        assertEquals("    c\n    d\n    c\n    d\n", applied.updated)
    }

    @Test fun lineTrimmedKeepsNewTextLineEndings() {
        // The combination the Dart suite pinned in 20b1147: CRLF content, an
        // oldText whose indentation is gone (so line_trimmed matches and the
        // re-indent runs), and a CRLF newText. This port keeps the inserted
        // text's own endings; normalising them would leave a CRLF file with
        // mixed endings, which is the defect this port refuses to copy.
        val original = "fun main() {\r\n    println(\"a\")\r\n    println(\"b\")\r\n}\r\n"
        val result = EditMatchers.applyEdit(
            original,
            "println(\"a\")\r\nprintln(\"b\")",
            "println(\"c\")\r\nprintln(\"d\")",
        )
        val applied = result as EditApplied
        assertEquals(EditStrategy.LINE_TRIMMED, applied.strategy)
        assertEquals(1, applied.replacements)
        assertEquals(
            "fun main() {\r\n    println(\"c\")\r\n    println(\"d\")\r\n}\r\n",
            applied.updated,
        )
        assertNotEquals(
            "fun main() {\r\n    println(\"c\")\n    println(\"d\")\r\n}\r\n",
            applied.updated,
        )
    }

    @Test fun blockAnchorMatchesFirstAndLastLinesAndIgnoresTheMiddle() {
        val original = "line1\nCHANGED\nline3\n"
        val result = EditMatchers.applyEdit(
            original, "line1\nold middle\nline3\n", "line1\nNEW\nline3\n",
        )
        val applied = result as EditApplied
        assertEquals(EditStrategy.BLOCK_ANCHOR, applied.strategy)
        assertEquals("line1\nNEW\nline3\n", applied.updated)
    }

    @Test fun blockAnchorRequiresAtLeastThreeLines() {
        val result = EditMatchers.applyEdit("a\nb\n", "a\nX", "a\nY")
        assertTrue(result is EditFailed)
    }

    @Test fun blockAnchorIsAmbiguousAcrossTwoBlocks() {
        val original = "start\nm1\nend\nstart\nm2\nend\n"
        val result = EditMatchers.applyEdit(original, "start\nxxx\nend", "start\nYYY\nend")
        val failed = result as EditFailed
        assertTrue(failed.failure is EditAmbiguous)
        assertEquals(EditStrategy.BLOCK_ANCHOR, (failed.failure as EditAmbiguous).strategy)
        assertTrue(failed.message.contains("strategy: block_anchor"))
        assertTrue(failed.message.contains("replace_all=true"))
    }

    @Test fun notFoundMessageIsReadyToSendToTheModel() {
        val result = EditMatchers.applyEdit("nothing here", "missing", "x")
        val failed = result as EditFailed
        assertTrue(failed.failure is EditNotFound)
        assertEquals(
            "old_string was not found, even with whitespace-tolerant matching; " +
                "read the file again and copy old_string exactly from its current content",
            failed.message,
        )
    }
}
