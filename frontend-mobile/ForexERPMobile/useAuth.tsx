import React, { createContext, useContext, useState, useEffect, ReactNode } from 'react';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { authApi } from '../services/api';
import { User, LoginCredentials } from '../types';

interface AuthContextType {
  user: User | null;
  pin: string;
  isLoading: boolean;
  isAuthenticated: boolean;
  login: (credentials: LoginCredentials) => Promise<void>;
  logout: () => Promise<void>;
  savePin: (pin: string) => Promise<void>;
}

const AuthContext = createContext<AuthContextType | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [pin, setPin] = useState('');
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    // Verificar sesión guardada al arrancar
    (async () => {
      try {
        const token = await AsyncStorage.getItem('access_token');
        const savedPin = await AsyncStorage.getItem('user_pin');
        if (token) {
          const me = await authApi.getMe();
          setUser(me);
          if (savedPin) setPin(savedPin);
        }
      } catch {
        await authApi.logout();
      } finally {
        setIsLoading(false);
      }
    })();
  }, []);

  const login = async (credentials: LoginCredentials) => {
    await authApi.login(credentials);
    const me = await authApi.getMe();
    setUser(me);
    setPin(credentials.pin);
    await AsyncStorage.setItem('user_pin', credentials.pin);
  };

  const logout = async () => {
    await authApi.logout();
    setUser(null);
    setPin('');
  };

  const savePin = async (newPin: string) => {
    setPin(newPin);
    await AsyncStorage.setItem('user_pin', newPin);
  };

  return (
    <AuthContext.Provider
      value={{ user, pin, isLoading, isAuthenticated: !!user, login, logout, savePin }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
