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

class _MainScreenState extends State<MainScreen> {
  int _currentIndex = 0;
  static const platform = MethodChannel('io.github.Mike666wq.czuconnect/guard');
  
  String _status = '未连接';
  bool _guardRunning = false;
  final List<String> _logs = [];
  
  final _usernameController = TextEditingController();
  final _passwordController = TextEditingController();
  String _selectedIsp = 'cmcc';

  @override
  void initState() {
    super.initState();
    _loadConfig();
    _refreshStatus();
  }

  Future<void> _loadConfig() async {
    final prefs = await SharedPreferences.getInstance();
    setState(() {
      _usernameController.text = prefs.getString('username') ?? '';
      _passwordController.text = prefs.getString('password') ?? '';
      _selectedIsp = prefs.getString('isp') ?? 'cmcc';
    });
  }

  Future<void> _saveConfig() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('username', _usernameController.text);
    await prefs.setString('password', _passwordController.text);
    await prefs.setString('isp', _selectedIsp);
    _addLog('配置已保存');
  }

  Future<void> _refreshStatus() async {
    try {
      final result = await platform.invokeMethod<Map<dynamic, dynamic>>('getStatus');
      if (result != null && mounted) {
        setState(() {
          _status = result['status'] as String? ?? '未知';
          _guardRunning = result['running'] as bool? ?? false;
        });
      }
    } catch (e) {
      _addLog('状态查询失败: $e');
    }
  }

  Future<void> _connectNow() async {
    _addLog('开始连接...');
    try {
      await _saveConfig();
      final result = await platform.invokeMethod<String>('connectNow', {
        'username': _usernameController.text,
        'password': _passwordController.text,
        'isp': _selectedIsp,
      });
      _addLog(result ?? '连接请求已发送');
      await _refreshStatus();
    } catch (e) {
      _addLog('连接失败: $e');
    }
  }

  Future<void> _toggleGuard() async {
    try {
      if (_guardRunning) {
        await platform.invokeMethod('stopGuard');
        _addLog('守护服务已停止');
      } else {
        await _saveConfig();
        await platform.invokeMethod('startGuard');
        _addLog('守护服务已启动');
      }
      await _refreshStatus();
    } catch (e) {
      _addLog('操作失败: $e');
    }
  }

  void _addLog(String message) {
    if (!mounted) return;
    setState(() {
      _logs.insert(0, '${DateTime.now().toString().substring(11, 19)} $message');
      if (_logs.length > 100) _logs.removeLast();
    });
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
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Icon(
              _guardRunning ? Icons.wifi : Icons.wifi_off,
              size: 120,
              color: _guardRunning ? Colors.green : Colors.grey,
            ),
            const SizedBox(height: 24),
            Text(
              _status,
              textAlign: TextAlign.center,
              style: Theme.of(context).textTheme.headlineMedium,
            ),
            const SizedBox(height: 8),
            Text(
              _guardRunning ? '守护中' : '未守护',
              textAlign: TextAlign.center,
              style: Theme.of(context).textTheme.bodyLarge?.copyWith(
                color: Colors.grey,
              ),
            ),
            const SizedBox(height: 48),
            FilledButton.icon(
              onPressed: _connectNow,
              icon: const Icon(Icons.link),
              label: const Text('立即连接'),
              style: FilledButton.styleFrom(
                padding: const EdgeInsets.all(16),
              ),
            ),
            const SizedBox(height: 16),
            OutlinedButton.icon(
              onPressed: _toggleGuard,
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
            controller: _usernameController,
            decoration: const InputDecoration(
              labelText: '学号/账号',
              border: OutlineInputBorder(),
              prefixIcon: Icon(Icons.person),
            ),
          ),
          const SizedBox(height: 16),
          TextField(
            controller: _passwordController,
            obscureText: true,
            decoration: const InputDecoration(
              labelText: '密码',
              border: OutlineInputBorder(),
              prefixIcon: Icon(Icons.lock),
            ),
          ),
          const SizedBox(height: 16),
          DropdownButtonFormField<String>(
            value: _selectedIsp,
            decoration: const InputDecoration(
              labelText: '运营商',
              border: OutlineInputBorder(),
              prefixIcon: Icon(Icons.cell_tower),
            ),
            items: const [
              DropdownMenuItem(value: 'cmcc', child: Text('中国移动')),
              DropdownMenuItem(value: 'unicom', child: Text('中国联通')),
              DropdownMenuItem(value: 'telecom', child: Text('中国电信')),
            ],
            onChanged: (value) {
              if (value != null) setState(() => _selectedIsp = value);
            },
          ),
          const SizedBox(height: 24),
          FilledButton.icon(
            onPressed: _saveConfig,
            icon: const Icon(Icons.save),
            label: const Text('保存配置'),
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
                    _logs[index],
                    style: const TextStyle(fontFamily: 'monospace', fontSize: 12),
                  ),
                );
              },
            ),
    );
  }

  @override
  void dispose() {
    _usernameController.dispose();
    _passwordController.dispose();
    super.dispose();
  }
}
