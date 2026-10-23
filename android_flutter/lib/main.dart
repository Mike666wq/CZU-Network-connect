import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  runApp(const CzuConnectApp());
}

class CzuConnectApp extends StatelessWidget {
  const CzuConnectApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: '校园网助手',
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(
          seedColor: const Color(0xFF2196F3),
          brightness: Brightness.dark,
        ),
        useMaterial3: true,
      ),
      home: const MainScreen(),
    );
  }
}

class MainScreen extends StatefulWidget {
  const MainScreen({super.key});

  @override
  State<MainScreen> createState() => _MainScreenState();
}

class _MainScreenState extends State<MainScreen> with WidgetsBindingObserver {
  int _currentIndex = 0;
  static const platform = MethodChannel('io.github.Mike666wq.czuconnect/guard');
  static const _isps = ['-1', '', '@cmcc', '@unicom', '@telecom'];
  static const _scenes = ['auto', 'public', 'dorm'];
  static const _legacyKeys = ['username', 'password', 'isp', 'scene'];
  static const _statusLabels = {
    'waiting': '等待检查',
    'paused': '自动检查已暂停',
    'stopped': '检查已停止',
    'checking': '正在检查网络',
    'online': '互联网已连通',
    'authenticated': '校园网已认证',
    'portal': '检测到校园认证门户',
    'needs_config': '需要检查配置',
    'auth_blocked': '认证被拒绝，等待重试',
    'error': '暂时无法检查网络',
  };
  static const _messageLabels = {
    'Waiting for a network check': '等待网络检查',
    'Automatic checks paused': '自动检查已暂停',
    'Automatic checks stopped': '自动检查已停止',
    'Checking network': '正在检查网络',
    'Internet is available': '互联网已连通',
    'Campus authentication and Internet verified': '校园网认证及互联网检查通过',
    'Campus portal available; waiting for Internet': '已识别校园门户，等待互联网连通',
    'Check account and campus configuration': '请检查账号及校园网配置',
    'Authentication refused; waiting before retry': '认证被拒绝，等待重试',
    'Network check temporarily unavailable': '网络检查暂时不可用',
  };

  String _status = '等待状态';
  String _message = '';
  String _coreVersion = '未知';
  String _notice = '';
  bool _guardRunning = false;
  bool _online = false;
  bool _exactAlarmAllowed = false;
  bool _batteryExempt = false;
  bool _busy = true;
  bool _configLoaded = false;
  bool _statusInFlight = false;
  bool _foreground = true;
  int? _nextSeconds;
  List<String> _logs = [];
  final Set<String> _secrets = {};
  Timer? _pollTimer;

  final _usernameController = TextEditingController();
  final _passwordController = TextEditingController();
  String _selectedIsp = '-1';
  String _selectedScene = 'auto';

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    final lifecycle = WidgetsBinding.instance.lifecycleState;
    _foreground = lifecycle == null || lifecycle == AppLifecycleState.resumed;
    unawaited(_initialize());
  }

  Future<void> _initialize() async {
    try {
      await _loadConfig();
    } catch (_) {
      if (mounted) setState(() => _notice = '配置读取失败，请重试');
    }
    if (!mounted) return;
    await _refreshStatus();
    if (!mounted) return;
    setState(() => _busy = false);
    _startPolling();
  }

  void _startPolling() {
    _pollTimer?.cancel();
    if (!mounted || !_foreground) return;
    _pollTimer = Timer.periodic(const Duration(seconds: 2), (_) {
      if (!_busy) unawaited(_refreshStatus());
    });
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    _foreground = state == AppLifecycleState.resumed;
    _pollTimer?.cancel();
    if (_foreground) {
      if (!_busy) unawaited(_refreshStatus());
      _startPolling();
    }
  }

  String _string(dynamic value, [String fallback = '']) {
    return value is String ? value : fallback;
  }

  String _isp(dynamic value, {bool legacy = false}) {
    if (legacy) {
      switch (value) {
        case 'cmcc':
          return '@cmcc';
        case 'unicom':
          return '@unicom';
        case 'telecom':
          return '@telecom';
      }
    }
    return _isps.contains(value) ? value as String : '-1';
  }

  String _scene(dynamic value) {
    return _scenes.contains(value) ? value as String : 'auto';
  }

  Future<void> _loadConfig() async {
    final result = await platform.invokeMapMethod<String, dynamic>('getConfig');
    if (!mounted) return;
    if (result == null) throw const FormatException();
    var config = <String, String>{
      'username': _string(result['username']),
      'password': _string(result['password']),
      'isp': _isp(result['isp']),
      'scene': _scene(result['scene']),
    };
    _rememberSecrets(config);
    final nativeConfigured = config['username']!.isNotEmpty ||
        config['password']!.isNotEmpty ||
        config['isp'] != '-1' ||
        config['scene'] != 'auto';

    if (!nativeConfigured) {
      final prefs = await SharedPreferences.getInstance();
      if (!mounted) return;
      if (_legacyKeys.any(prefs.containsKey)) {
        // The old UI defaulted to Mobile; only migrate that default for a
        // persisted legacy configuration, never for a fresh installation.
        config = {
          'username': prefs.getString('username') ?? '',
          'password': prefs.getString('password') ?? '',
          'isp': _isp(prefs.getString('isp') ?? 'cmcc', legacy: true),
          'scene': _scene(prefs.getString('scene')),
        };
        _rememberSecrets(config);
        await platform.invokeMethod<void>('saveConfig', config);
        if (!mounted) return;
        // Remove legacy credentials only after the native private store accepts
        // them. A failed migration leaves the original values available to retry.
        for (final key in _legacyKeys) {
          await prefs.remove(key);
          if (!mounted) return;
        }
      }
    }
    if (!mounted) return;
    setState(() {
      _usernameController.text = config['username']!;
      _passwordController.text = config['password']!;
      _selectedIsp = config['isp']!;
      _selectedScene = config['scene']!;
      _configLoaded = true;
    });
  }

  Future<void> _saveConfig() async {
    final config = <String, String>{
      'username': _usernameController.text.trim(),
      'password': _passwordController.text,
      'isp': _selectedIsp,
      'scene': _selectedScene,
    };
    _rememberSecrets(config);
    await platform.invokeMethod<void>('saveConfig', config);
  }

  void _rememberSecrets(Map<String, String> config) {
    for (final key in ['username', 'password']) {
      final value = config[key];
      if (value != null && value.isNotEmpty) _secrets.add(value);
    }
  }

  String _redact(String text) {
    final secrets = {
      ..._secrets,
      _usernameController.text,
      _passwordController.text,
    }.where((value) => value.isNotEmpty).toList()
      ..sort((a, b) => b.length.compareTo(a.length));
    for (final secret in secrets) {
      text = text.replaceAll(secret, '[已隐藏]');
    }
    return text;
  }

  String _statusLabel(dynamic value) {
    final text = _string(value);
    final label = _statusLabels[text.toLowerCase()];
    if (label != null) return label;
    return RegExp(r'[\u3400-\u9fff]').hasMatch(text)
        ? _redact(text)
        : '状态待更新';
  }

  Future<void> _refreshStatus() async {
    if (!mounted || !_foreground || _statusInFlight) return;
    _statusInFlight = true;
    try {
      final result = await platform.invokeMapMethod<String, dynamic>('getStatus');
      if (!mounted) return;
      if (result == null) throw const FormatException();
      final logs = result['logs'];
      final seconds = result['nextSeconds'];
      setState(() {
        _status = _statusLabel(result['status']);
        final message = _string(result['message']);
        _message = _redact(_messageLabels[message] ?? message);
        _guardRunning = result['running'] == true;
        _online = result['online'] == true;
        final version = _string(result['coreVersion']);
        _coreVersion = version.isEmpty ? '未知' : _redact(version);
        _nextSeconds = seconds is int && seconds >= 0 ? seconds : null;
        _exactAlarmAllowed = result['exactAlarmAllowed'] == true;
        _batteryExempt = result['batteryExempt'] == true;
        _logs = logs is List
            ? logs.whereType<String>().map(_redact).toList()
            : [];
        if (_notice == '状态查询失败，请重试') _notice = '';
      });
    } catch (_) {
      if (mounted) setState(() => _notice = '状态查询失败，请重试');
    } finally {
      _statusInFlight = false;
    }
  }

  Future<void> _runAction(
    Future<void> Function() action,
    String success,
  ) async {
    if (!mounted || _busy) return;
    setState(() {
      _busy = true;
      _notice = '';
    });
    try {
      await action();
      if (!mounted) return;
      setState(() => _notice = success);
      await _refreshStatus();
    } catch (_) {
      if (mounted) setState(() => _notice = '操作失败，请重试');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _connectNow() {
    return _runAction(() async {
      await _saveConfig();
      if (!mounted) return;
      await platform.invokeMethod<void>('connectNow');
    }, '连接及守护请求已发送，检查已排队');
  }

  Future<void> _toggleGuard() {
    return _runAction(() async {
      if (_guardRunning) {
        await platform.invokeMethod<void>('stopGuard');
      } else {
        await _saveConfig();
        if (!mounted) return;
        await platform.invokeMethod<void>('startGuard');
      }
    }, '守护请求已发送');
  }

  Future<void> _openSettings(String method) {
    return _runAction(
      () => platform.invokeMethod<void>(method),
      '权限请求已发送，返回应用后自动刷新',
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: IndexedStack(
        index: _currentIndex,
        children: [
          _buildStatusPage(),
          _buildSettingsPage(),
          _buildLogsPage(),
        ],
      ),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _currentIndex,
        onDestinationSelected: (index) {
          setState(() => _currentIndex = index);
        },
        destinations: const [
          NavigationDestination(icon: Icon(Icons.wifi), label: '状态'),
          NavigationDestination(icon: Icon(Icons.settings), label: '设置'),
          NavigationDestination(icon: Icon(Icons.list), label: '日志'),
        ],
      ),
    );
  }

  Widget _buildStatusPage() {
    return SafeArea(
      child: Padding(
        padding: const EdgeInsets.all(24.0),
        child: ListView(
          shrinkWrap: true,
          children: [
            Icon(
              _online ? Icons.wifi : Icons.wifi_off,
              size: 120,
              color: _online ? Colors.green : Colors.grey,
            ),
            const SizedBox(height: 24),
            Text(
              _redact(_status),
              textAlign: TextAlign.center,
              style: Theme.of(context).textTheme.headlineMedium,
            ),
            const SizedBox(height: 8),
            Text(
              _online ? '网络在线' : '网络离线',
              textAlign: TextAlign.center,
            ),
            if (_message.isNotEmpty)
              Text(_redact(_message), textAlign: TextAlign.center),
            Text(
              _guardRunning ? '守护中' : '未守护',
              textAlign: TextAlign.center,
              style: Theme.of(context).textTheme.bodyLarge?.copyWith(
                color: Colors.grey,
              ),
            ),
            if (_guardRunning && _nextSeconds != null)
              Text('下次检查：$_nextSeconds 秒', textAlign: TextAlign.center),
            const SizedBox(height: 8),
            Text('核心版本：${_redact(_coreVersion)}', textAlign: TextAlign.center),
            if (_notice.isNotEmpty)
              Padding(
                padding: const EdgeInsets.only(top: 16),
                child: Text(_notice, textAlign: TextAlign.center),
              ),
            const SizedBox(height: 32),
            FilledButton.icon(
              key: const ValueKey('connect'),
              onPressed: _busy || !_configLoaded ? null : _connectNow,
              icon: const Icon(Icons.link),
              label: const Text('立即连接并守护'),
              style: FilledButton.styleFrom(
                padding: const EdgeInsets.all(16),
              ),
            ),
            const SizedBox(height: 16),
            OutlinedButton.icon(
              key: const ValueKey('guard'),
              onPressed: _busy || (!_guardRunning && !_configLoaded)
                  ? null
                  : _toggleGuard,
              icon: Icon(_guardRunning ? Icons.stop : Icons.play_arrow),
              label: Text(_guardRunning ? '停止守护' : '启动守护'),
              style: OutlinedButton.styleFrom(
                padding: const EdgeInsets.all(16),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildSettingsPage() {
    return SafeArea(
      child: ListView(
        padding: const EdgeInsets.all(16.0),
        children: [
          Text('账号配置', style: Theme.of(context).textTheme.titleLarge),
          const SizedBox(height: 16),
          TextField(
            key: const ValueKey('username'),
            enabled: !_busy && _configLoaded,
            controller: _usernameController,
            decoration: const InputDecoration(
              labelText: '学号/账号',
              border: OutlineInputBorder(),
              prefixIcon: Icon(Icons.person),
            ),
          ),
          const SizedBox(height: 16),
          TextField(
            key: const ValueKey('password'),
            enabled: !_busy && _configLoaded,
            controller: _passwordController,
            obscureText: true,
            autocorrect: false,
            enableSuggestions: false,
            decoration: const InputDecoration(
              labelText: '密码',
              border: OutlineInputBorder(),
              prefixIcon: Icon(Icons.lock),
            ),
          ),
          const SizedBox(height: 16),
          DropdownButtonFormField<String>(
            key: ValueKey('isp-$_selectedIsp'),
            value: _selectedIsp,
            decoration: const InputDecoration(
              labelText: '运营商',
              border: OutlineInputBorder(),
              prefixIcon: Icon(Icons.cell_tower),
            ),
            items: const [
              DropdownMenuItem(value: '-1', child: Text('未选择')),
              DropdownMenuItem(value: '', child: Text('校园网')),
              DropdownMenuItem(value: '@cmcc', child: Text('中国移动')),
              DropdownMenuItem(value: '@unicom', child: Text('中国联通')),
              DropdownMenuItem(value: '@telecom', child: Text('中国电信')),
            ],
            onChanged: _busy || !_configLoaded
                ? null
                : (value) {
                    if (value != null) setState(() => _selectedIsp = value);
                  },
          ),
          const SizedBox(height: 16),
          DropdownButtonFormField<String>(
            key: ValueKey('scene-$_selectedScene'),
            value: _selectedScene,
            decoration: const InputDecoration(
              labelText: '认证场景',
              border: OutlineInputBorder(),
              prefixIcon: Icon(Icons.location_on),
            ),
            items: const [
              DropdownMenuItem(value: 'auto', child: Text('自动识别')),
              DropdownMenuItem(value: 'public', child: Text('公共网')),
              DropdownMenuItem(value: 'dorm', child: Text('宿舍网')),
            ],
            onChanged: _busy || !_configLoaded
                ? null
                : (value) {
                    if (value != null) setState(() => _selectedScene = value);
                  },
          ),
          const SizedBox(height: 24),
          FilledButton.icon(
            key: const ValueKey('save'),
            onPressed: _busy || !_configLoaded
                ? null
                : () => _runAction(_saveConfig, '配置已保存'),
            icon: const Icon(Icons.save),
            label: const Text('保存配置'),
          ),
          if (!_configLoaded)
            TextButton(
              key: const ValueKey('reloadConfig'),
              onPressed: _busy
                  ? null
                  : () => _runAction(_loadConfig, '配置已读取'),
              child: const Text('重试读取配置'),
            ),
          if (_notice.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(top: 12),
              child: Text(_notice),
            ),
          const SizedBox(height: 24),
          Text('后台运行权限', style: Theme.of(context).textTheme.titleLarge),
          Text(_batteryExempt ? '电池优化：已豁免' : '电池优化：未豁免'),
          OutlinedButton(
            key: const ValueKey('batterySettings'),
            onPressed: _busy ? null : () => _openSettings('openBatterySettings'),
            child: const Text('电池优化设置'),
          ),
          Text(_exactAlarmAllowed ? '精确闹钟：已允许' : '精确闹钟：未允许'),
          OutlinedButton(
            key: const ValueKey('alarmSettings'),
            onPressed: _busy ? null : () => _openSettings('openAlarmSettings'),
            child: const Text('精确闹钟设置'),
          ),
          OutlinedButton(
            key: const ValueKey('notifications'),
            onPressed: _busy ? null : () => _openSettings('requestNotifications'),
            child: const Text('请求通知权限'),
          ),
        ],
      ),
    );
  }

  Widget _buildLogsPage() {
    return SafeArea(
      child: _logs.isEmpty
          ? const Center(child: Text('暂无日志'))
          : ListView.builder(
              padding: const EdgeInsets.all(16.0),
              itemCount: _logs.length,
              itemBuilder: (context, index) {
                return Padding(
                  padding: const EdgeInsets.symmetric(vertical: 4.0),
                  child: Text(
                    _redact(_logs[index]),
                    style: const TextStyle(fontFamily: 'monospace', fontSize: 12),
                  ),
                );
              },
            ),
    );
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _pollTimer?.cancel();
    _usernameController.dispose();
    _passwordController.dispose();
    super.dispose();
  }
}
