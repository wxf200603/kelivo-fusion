package com.psyche.kelivo.workspace.edit

/**
 * Kotlin-side port of `lib/core/services/workspace/edit_matchers.dart`, which
 * is itself a port of RikkaHub `TextReplacers.kt`: exact -> line-trimmed ->
 * block-anchor.
 *
 * This object exists because the Kotlin host cannot call back into Dart:
 * `Tools.Files.apply` arrives over QuickJS and has to be answered in
 * [com.psyche.kelivo.workspace.KelivoWorkspaceHost] without crossing back into
 * the Flutter layer. Keep this file and `edit_matchers.dart` in step;
 * [EditMatchersTest] and `edit_matchers_test.dart` describe the same
 * behaviour, case for case.
 *
 * Contract:
 *   - The first strategy that matches wins; a later strategy never sees a file
 *     the earlier one already matched.
 *   - `replaceAll = false` with more than one match is [EditAmbiguous], not a
 *     silent first-wins.
 *   - A failure never mutates the input; the caller writes only on
 *     [EditApplied].
 */
internal enum class EditStrategy(val id: String) {
    EXACT("exact"),
    LINE_TRIMMED("line_trimmed"),
    BLOCK_ANCHOR("block_anchor"),
}

internal sealed class EditFailure

internal object EditNotFound : EditFailure()

internal class EditAmbiguous(
    val count: Int,
    val strategy: EditStrategy,
) : EditFailure()

internal sealed class EditOutcome {
    /** Ready-to-send explanation for the model. Empty on success. */
    abstract val message: String
}

internal class EditApplied(
    val updated: String,
    val replacements: Int,
    val strategy: EditStrategy,
) : EditOutcome() {
    override val message: String = ""
}

internal class EditFailed(
    val failure: EditFailure,
    override val message: String,
) : EditOutcome()

internal const val EDIT_NOT_FOUND_MESSAGE =
    "old_string was not found, even with whitespace-tolerant matching; " +
        "read the file again and copy old_string exactly from its current content"

internal fun editAmbiguousMessage(count: Int, strategy: EditStrategy): String =
    "old_string matches $count locations (strategy: ${strategy.id}); " +
        "add more surrounding context to make it unique, or set replace_all=true"

internal object EditMatchers {

    /** One located span and the text that replaces it. */
    private class Match(
        val start: Int,
        val endExclusive: Int,
        val replacement: String,
    )

    fun applyEdit(
        original: String,
        oldText: String,
        newText: String,
        replaceAll: Boolean = false,
    ): EditOutcome {
        if (oldText.isEmpty()) return EditFailed(EditNotFound, EDIT_NOT_FOUND_MESSAGE)
        for (strategy in EditStrategy.entries) {
            val matches = findMatches(original, oldText, newText, strategy)
            if (matches.isEmpty()) continue
            if (!replaceAll && matches.size > 1) {
                return EditFailed(
                    EditAmbiguous(matches.size, strategy),
                    editAmbiguousMessage(matches.size, strategy),
                )
            }
            val chosen = if (replaceAll) {
                matches
            } else {
                listOf(matches.reduce { a, b -> if (a.start <= b.start) a else b })
            }
            val applied = chosen.sortedBy { it.start }
            val buffer = StringBuilder()
            var cursor = 0
            for (match in applied) {
                buffer.append(original, cursor, match.start)
                buffer.append(match.replacement)
                cursor = match.endExclusive
            }
            buffer.append(original, cursor, original.length)
            return EditApplied(buffer.toString(), applied.size, strategy)
        }
        return EditFailed(EditNotFound, EDIT_NOT_FOUND_MESSAGE)
    }

    private fun findMatches(
        content: String,
        oldText: String,
        newText: String,
        strategy: EditStrategy,
    ): List<Match> = when (strategy) {
        EditStrategy.EXACT -> exactMatches(content, oldText, newText)
        EditStrategy.LINE_TRIMMED -> lineWindowMatches(
            content, oldText, newText,
            minLines = 1,
            requireNonBlankOld = true,
            requireNonEmptyAnchors = false,
            windowMatches = { window, old -> window == old },
        )
        EditStrategy.BLOCK_ANCHOR -> lineWindowMatches(
            content, oldText, newText,
            minLines = 3,
            requireNonBlankOld = true,
            requireNonEmptyAnchors = true,
            windowMatches = { window, old ->
                window.first() == old.first() && window.last() == old.last()
            },
        )
    }

    private fun exactMatches(
        content: String,
        oldText: String,
        newText: String,
    ): List<Match> {
        val matches = mutableListOf<Match>()
        var index = content.indexOf(oldText)
        while (index >= 0) {
            matches.add(Match(index, index + oldText.length, newText))
            index = content.indexOf(oldText, index + oldText.length)
        }
        return matches
    }

    private fun lineWindowMatches(
        content: String,
        oldText: String,
        newText: String,
        minLines: Int,
        requireNonBlankOld: Boolean,
        requireNonEmptyAnchors: Boolean,
        windowMatches: (List<String>, List<String>) -> Boolean,
    ): List<Match> {
        val rawOldLines = oldText.split('\n')
        val dropTrailingEmpty = rawOldLines.size > 1 && rawOldLines.last().isEmpty()
        val oldLines = if (dropTrailingEmpty) rawOldLines.dropLast(1) else rawOldLines
        val oldTrimmed = oldLines.map { it.trim() }
        if (oldLines.size < minLines) return emptyList()
        if (requireNonBlankOld && oldTrimmed.all { it.isEmpty() }) return emptyList()
        if (requireNonEmptyAnchors &&
            (oldTrimmed.first().isEmpty() || oldTrimmed.last().isEmpty())
        ) {
            return emptyList()
        }
        val adjustedNewText =
            if (dropTrailingEmpty) removeOneTrailingNewline(newText) else newText
        val contentLines = splitLinesWithOffsets(content)
        val matches = mutableListOf<Match>()
        var index = 0
        while (index + oldLines.size <= contentLines.size) {
            val window = contentLines.subList(index, index + oldLines.size)
            val windowTrimmed = window.map { it.text.trim() }
            if (windowMatches(windowTrimmed, oldTrimmed)) {
                val replacement = reindent(
                    adjustedNewText,
                    indentOf(oldLines.first()),
                    indentOf(window.first().text),
                )
                matches.add(Match(window.first().start, window.last().endExclusive, replacement))
                index += oldLines.size
            } else {
                index++
            }
        }
        return matches
    }

    private class LineWithOffset(val start: Int, val endExclusive: Int, val text: String)

    /**
     * Split on `\n`, treating a preceding `\r` as part of the line ending so
     * offsets stay on the logical line text (RikkaHub `splitLinesWithOffsets`).
     */
    private fun splitLinesWithOffsets(content: String): List<LineWithOffset> {
        val lines = mutableListOf<LineWithOffset>()
        var start = 0
        var index = 0
        while (index < content.length) {
            if (content[index] == '\n') {
                val end = if (index > start && content[index - 1] == '\r') index - 1 else index
                lines.add(LineWithOffset(start, end, content.substring(start, end)))
                start = index + 1
            }
            index++
        }
        lines.add(LineWithOffset(start, content.length, content.substring(start)))
        return lines
    }

    private fun indentOf(line: String): String {
        var i = 0
        while (i < line.length) {
            val unit = line[i]
            if (unit != ' ' && unit != '\t') break
            i++
        }
        return line.substring(0, i)
    }

    private fun reindent(text: String, oldIndent: String, newIndent: String): String {
        if (oldIndent == newIndent) return text
        return text.split('\n').joinToString("\n") { line ->
            when {
                line.trim().isEmpty() -> line
                line.startsWith(oldIndent) -> newIndent + line.substring(oldIndent.length)
                else -> line
            }
        }
    }

    private fun removeOneTrailingNewline(text: String): String = when {
        text.endsWith("\r\n") -> text.substring(0, text.length - 2)
        text.endsWith("\n") -> text.substring(0, text.length - 1)
        else -> text
    }
}
