export * from './identity.service';
import { IdentityService } from './identity.service';
export * from './identity.serviceInterface';
export * from './system.service';
import { SystemService } from './system.service';
export * from './system.serviceInterface';
export const APIS = [IdentityService, SystemService];
