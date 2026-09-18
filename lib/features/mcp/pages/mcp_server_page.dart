import 'dart:async';

import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../../core/services/mcp/server/mcp_server_service.dart';
import '../../../icons/lucide_adapter.dart';
import '../../../l10n/app_localizations.dart';
import '../../../shared/widgets/ios_switch.dart';
import '../../../shared/widgets/section_card.dart';
import '../../../shared/widgets/snackbar.dart';
import '../../../theme/app_font_weights.dart';
import 'package:Kelivo/theme/app_semantic_colors.dart';

/// Settings for the MCP server this app *serves*.
///
/// Kept separate from `McpPage` on purpose: that page manages the servers this
/// app *connects to*. The two directions of trust are opposite, so sharing one
/// list would make "add" ambiguous and would sit a switch that exposes a root
/// shell next to switches that consume somebody else's tools.
class McpServerPage extends StatelessWidget {
  const McpServerPage({super.key});

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final l10n = AppLocalizations.of(context)!;
    final service = McpServerService.instance;

    return Scaffold(
      appBar: AppBar(
        leading: Tooltip(
          message: l10n.mcpPageBackTooltip,
          child: IconButton(
            icon: Icon(Lucide.ArrowLeft, size: 22, color: cs.onSurface),
            onPressed: () => Navigator.of(context).maybePop(),
          ),
        ),
        title: Text(l10n.mcpServerPageTitle),
      ),
      body: ListenableBuilder(
        listenable: service,
        builder: (context, _) => ListView(
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 24),
          children: [
            _ServerCard(service: service, l10n: l10n),
            const SizedBox(height: 14),
            _EndpointsCard(service: service, l10n: l10n),
            const SizedBox(height: 14),
            _TokenCard(service: service, l10n: l10n),
            const SizedBox(height: 14),
            _NetworkCard(service: service, l10n: l10n),
            const SizedBox(height: 14),
            _PortCard(service: service, l10n: l10n),
            if (service.lastError != null) ...[
              const SizedBox(height: 14),
              _ErrorCard(message: service.lastError!, l10n: l10n),
            ],
          ],
        ),
      ),
    );
  }
}

/// The on/off switch plus what it currently means.
class _ServerCard extends StatelessWidget {
  const _ServerCard({required this.service, required this.l10n});

  final McpServerService service;
  final AppLocalizations l10n;

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final colors = context.appColors;
    final running = service.isRunning;

    return SectionCard(
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(14, 12, 14, 10),
          child: Row(
            children: [
              Icon(Lucide.SquareTerminal, size: 20, color: colors.success),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      l10n.mcpServerPageEnable,
                      style: TextStyle(
                        fontSize: 15,
                        fontWeight: AppFontWeights.emphasis,
                      ),
                    ),
                    const SizedBox(height: 3),
                    Text(
                      running
                          ? l10n.mcpServerPageStatusRunning
                          : l10n.mcpServerPageStatusStopped,
                      style: TextStyle(
                        fontSize: 12.5,
                        color: running
                            ? colors.success
                            : cs.onSurface.withValues(alpha: 0.6),
                      ),
                    ),
                  ],
                ),
              ),
              IosSwitch(
                value: service.enabled,
                onChanged: (value) => unawaited(service.setEnabled(value)),
                semanticLabel: l10n.mcpServerPageEnable,
              ),
            ],
          ),
        ),
        Padding(
          padding: const EdgeInsets.fromLTRB(14, 0, 14, 12),
          child: Text(
            l10n.mcpServerPageListenerHint,
            style: TextStyle(
              fontSize: 12.5,
              height: 1.45,
              color: cs.onSurface.withValues(alpha: 0.6),
            ),
          ),
        ),
      ],
    );
  }
}

/// The URLs to paste into a client.
class _EndpointsCard extends StatelessWidget {
  const _EndpointsCard({required this.service, required this.l10n});

  final McpServerService service;
  final AppLocalizations l10n;

  @override
  Widget build(BuildContext context) {
    return SectionCard(
      children: [
        _CardTitle(text: l10n.mcpServerPageEndpoints),
        _LinkRow(
          label: l10n.mcpServerPageTransportHttp,
          value: service.streamableUrl,
          l10n: l10n,
        ),
        _LinkRow(
          label: l10n.mcpServerPageTransportSse,
          value: service.sseUrl,
          l10n: l10n,
        ),
      ],
    );
  }
}

/// The bearer token, shown whole so it can be typed elsewhere if copying fails.
class _TokenCard extends StatelessWidget {
  const _TokenCard({required this.service, required this.l10n});

  final McpServerService service;
  final AppLocalizations l10n;

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;

    return SectionCard(
      children: [
        _CardTitle(text: l10n.mcpServerPageToken),
        Padding(
          padding: const EdgeInsets.fromLTRB(14, 4, 8, 4),
          child: Row(
            children: [
              Expanded(
                child: Text(
                  service.token,
                  style: TextStyle(
                    fontSize: 12,
                    height: 1.4,
                    color: cs.onSurface.withValues(alpha: 0.75),
                  ),
                ),
              ),
              _CopyButton(text: service.token, l10n: l10n),
              CupertinoButton(
                padding: const EdgeInsets.symmetric(
                  horizontal: 10,
                  vertical: 6,
                ),
                minimumSize: Size.zero,
                onPressed: () => unawaited(service.regenerateToken()),
                child: Icon(Lucide.RefreshCw, size: 15, color: cs.primary),
              ),
            ],
          ),
        ),
        Padding(
          padding: const EdgeInsets.fromLTRB(14, 0, 14, 12),
          child: Text(
            l10n.mcpServerPageTokenHint,
            style: TextStyle(
              fontSize: 12,
              height: 1.45,
              color: cs.onSurface.withValues(alpha: 0.55),
            ),
          ),
        ),
      ],
    );
  }
}

/// Loopback versus the LAN, and what to do about a client on a PC.
class _NetworkCard extends StatelessWidget {
  const _NetworkCard({required this.service, required this.l10n});

  final McpServerService service;
  final AppLocalizations l10n;

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final colors = context.appColors;

    return SectionCard(
      children: [
        _CardTitle(text: l10n.mcpServerPageNetwork),
        Padding(
          padding: const EdgeInsets.fromLTRB(14, 4, 14, 4),
          child: Row(
            children: [
              Expanded(
                child: Text(
                  l10n.mcpServerPageAllowLan,
                  style: TextStyle(
                    fontSize: 14,
                    fontWeight: AppFontWeights.emphasis,
                  ),
                ),
              ),
              IosSwitch(
                value: service.allowLan,
                onChanged: (value) => unawaited(service.setAllowLan(value)),
                semanticLabel: l10n.mcpServerPageAllowLan,
              ),
            ],
          ),
        ),
        Padding(
          padding: const EdgeInsets.fromLTRB(14, 0, 14, 10),
          child: Text(
            l10n.mcpServerPageAllowLanHint,
            style: TextStyle(
              fontSize: 12.5,
              height: 1.45,
              color: cs.onSurface.withValues(alpha: 0.6),
            ),
          ),
        ),
        // The PC case is the one that looks like a bug when it is not: a client
        // on another machine cannot reach the phone's loopback, so both answers
        // (forward the port, or listen on the LAN) are spelled out here.
        Container(
          margin: const EdgeInsets.fromLTRB(14, 0, 14, 12),
          padding: const EdgeInsets.fromLTRB(12, 10, 8, 10),
          decoration: BoxDecoration(
            color: colors.surfaceCardFill,
            borderRadius: BorderRadius.circular(10),
          ),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Icon(
                Lucide.Globe,
                size: 15,
                color: cs.onSurface.withValues(alpha: 0.6),
              ),
              const SizedBox(width: 9),
              Expanded(
                child: Text(
                  l10n.mcpServerPagePcHint,
                  style: TextStyle(
                    fontSize: 12,
                    height: 1.5,
                    color: cs.onSurface.withValues(alpha: 0.7),
                  ),
                ),
              ),
              _CopyButton(
                text: 'adb forward tcp:${service.port} tcp:${service.port}',
                l10n: l10n,
                iconOnly: true,
              ),
            ],
          ),
        ),
      ],
    );
  }
}

/// The listening port, edited through the same sheet shape as the timeout.
class _PortCard extends StatelessWidget {
  const _PortCard({required this.service, required this.l10n});

  final McpServerService service;
  final AppLocalizations l10n;

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final colors = context.appColors;

    return SectionCard(
      children: [
        _CardTitle(text: l10n.mcpServerPagePort),
        CupertinoButton(
          padding: const EdgeInsets.fromLTRB(14, 6, 8, 6),
          minimumSize: Size.zero,
          onPressed: () => showMcpPortSheet(context, service),
          child: Row(
            children: [
              Expanded(
                child: Text(
                  '${service.port}',
                  style: TextStyle(
                    fontSize: 14,
                    fontWeight: AppFontWeights.emphasis,
                  ),
                ),
              ),
              Icon(
                Lucide.Edit,
                size: 16,
                color: cs.onSurface.withValues(alpha: 0.55),
              ),
            ],
          ),
        ),
        Padding(
          padding: const EdgeInsets.fromLTRB(14, 0, 14, 6),
          child: Text(
            service.boundPort > 0
                ? '${l10n.mcpServerPageStatusRunning} :${service.boundPort}'
                : '',
            style: TextStyle(
              fontSize: 12,
              color: colors.success.withValues(alpha: 0.9),
            ),
          ),
        ),
      ],
    );
  }
}

/// Why the last start attempt failed, in the user's words rather than a stack.
class _ErrorCard extends StatelessWidget {
  const _ErrorCard({required this.message, required this.l10n});

  final String message;
  final AppLocalizations l10n;

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final colors = context.appColors;

    return SectionCard(
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(14, 12, 14, 12),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Icon(Lucide.KeyRound, size: 16, color: colors.warning),
              const SizedBox(width: 10),
              Expanded(
                child: Text(
                  message,
                  style: TextStyle(
                    fontSize: 12.5,
                    height: 1.45,
                    color: cs.onSurface.withValues(alpha: 0.8),
                  ),
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }
}

class _CardTitle extends StatelessWidget {
  const _CardTitle({required this.text});

  final String text;

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return Padding(
      padding: const EdgeInsets.fromLTRB(14, 12, 14, 4),
      child: Text(
        text,
        style: TextStyle(
          fontSize: 12,
          letterSpacing: 0.3,
          fontWeight: AppFontWeights.emphasis,
          color: cs.onSurface.withValues(alpha: 0.55),
        ),
      ),
    );
  }
}

/// One labelled value with a copy affordance — used for URLs and addresses.
class _LinkRow extends StatelessWidget {
  const _LinkRow({
    required this.label,
    required this.value,
    required this.l10n,
  });

  final String label;
  final String value;
  final AppLocalizations l10n;

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return Padding(
      padding: const EdgeInsets.fromLTRB(14, 4, 6, 4),
      child: Row(
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  label,
                  style: TextStyle(
                    fontSize: 13,
                    fontWeight: AppFontWeights.emphasis,
                  ),
                ),
                const SizedBox(height: 2),
                Text(
                  value,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(
                    fontSize: 12,
                    color: cs.onSurface.withValues(alpha: 0.65),
                  ),
                ),
              ],
            ),
          ),
          _CopyButton(text: value, l10n: l10n),
        ],
      ),
    );
  }
}

class _CopyButton extends StatelessWidget {
  const _CopyButton({
    required this.text,
    required this.l10n,
    this.iconOnly = false,
  });

  final String text;
  final AppLocalizations l10n;
  final bool iconOnly;

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return CupertinoButton(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
      minimumSize: Size.zero,
      onPressed: () async {
        await Clipboard.setData(ClipboardData(text: text));
        if (!context.mounted) return;
        showAppSnackBar(
          context,
          message: l10n.mcpServerPageCopied,
          type: NotificationType.success,
        );
      },
      child: iconOnly
          ? Icon(
              Lucide.Copy,
              size: 15,
              color: cs.onSurface.withValues(alpha: 0.6),
            )
          : Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Icon(Lucide.Copy, size: 15, color: cs.primary),
                const SizedBox(width: 4),
                Text(
                  l10n.mcpServerPageCopy,
                  style: TextStyle(fontSize: 12.5, color: cs.primary),
                ),
              ],
            ),
    );
  }
}

/// Edits the port, in the sheet shape the MCP timeout editor already uses.
Future<void> showMcpPortSheet(
  BuildContext context,
  McpServerService service,
) async {
  final l10n = AppLocalizations.of(context)!;
  final controller = TextEditingController(text: '${service.port}');

  await showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    backgroundColor: context.overlaySurface,
    shape: const RoundedRectangleBorder(
      borderRadius: BorderRadius.vertical(top: Radius.circular(16)),
    ),
    builder: (ctx) {
      final cs = Theme.of(ctx).colorScheme;
      final bottom = MediaQuery.of(ctx).viewInsets.bottom;

      Future<void> handleSave() async {
        FocusScope.of(ctx).unfocus();
        final port = int.tryParse(controller.text.trim());
        if (port == null || port < 1024 || port > 65535) {
          showAppSnackBar(
            ctx,
            message: l10n.mcpServerPagePortInvalid,
            type: NotificationType.warning,
          );
          return;
        }
        await service.setPort(port);
        if (ctx.mounted) Navigator.of(ctx).maybePop();
      }

      return Padding(
        padding: EdgeInsets.fromLTRB(16, 12, 16, 16 + bottom),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Center(
              child: Container(
                width: 48,
                height: 5,
                decoration: BoxDecoration(
                  color: cs.outlineVariant.withValues(alpha: 0.2),
                  borderRadius: BorderRadius.circular(999),
                ),
              ),
            ),
            const SizedBox(height: 10),
            Text(
              l10n.mcpServerPagePortTitle,
              style: TextStyle(
                fontSize: 17,
                fontWeight: AppFontWeights.emphasis,
              ),
              textAlign: TextAlign.center,
            ),
            const SizedBox(height: 14),
            TextField(
              controller: controller,
              keyboardType: TextInputType.number,
              inputFormatters: [FilteringTextInputFormatter.digitsOnly],
              decoration: InputDecoration(
                filled: true,
                fillColor: context.appColors.surfaceCard,
                border: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(12),
                  borderSide: BorderSide(
                    color: cs.outlineVariant.withValues(alpha: 0.4),
                  ),
                ),
                enabledBorder: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(12),
                  borderSide: BorderSide(
                    color: cs.outlineVariant.withValues(alpha: 0.4),
                  ),
                ),
                focusedBorder: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(12),
                  borderSide: BorderSide(
                    color: cs.primary.withValues(alpha: 0.5),
                  ),
                ),
                contentPadding: const EdgeInsets.symmetric(
                  horizontal: 12,
                  vertical: 12,
                ),
              ),
              onSubmitted: (_) => handleSave(),
            ),
            const SizedBox(height: 16),
            Row(
              children: [
                Expanded(
                  child: CupertinoButton(
                    padding: const EdgeInsets.symmetric(vertical: 12),
                    color: context.appColors.surfaceFill,
                    borderRadius: BorderRadius.circular(12),
                    onPressed: () => Navigator.of(ctx).maybePop(),
                    child: Text(
                      l10n.mcpPageClose,
                      style: TextStyle(color: cs.onSurface),
                    ),
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: CupertinoButton.filled(
                    padding: const EdgeInsets.symmetric(vertical: 12),
                    borderRadius: BorderRadius.circular(12),
                    onPressed: handleSave,
                    color: cs.primary,
                    child: Text(l10n.mcpServerEditSheetSave),
                  ),
                ),
              ],
            ),
          ],
        ),
      );
    },
  );
}
